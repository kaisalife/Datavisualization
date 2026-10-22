"""数据视图（DataView）核心：ViewSpec 数据模型与确定性标识。

一个 DataView 是「纯函数 × 不可变数据 → DataFrame」：

```text
view_id = sha256(source 指纹 + spec 规范化序列化 + engine_version)
```

同一 ViewSpec、同一输入、同一引擎版本 → 同一 view_id → 同一 DataFrame。
这是整个数据视图层唯一需要维护的不变量；缓存、审计、复用都建立在它之上。

spec 有两种 kind：

- ``sql``：一条只读 ``SELECT / WITH``（校验复用 ``sql_safety.ensure_read_only``），
  且必须含稳定排序（``ORDER BY``），除非显式声明 ``allow_unordered=True``；
- ``plugin``：已注册插件的 ``name + version + params`` 引用；插件本身是纯函数
  （见 ``registry.py``），禁止运行期提交函数体。

LLM 只允许生成 spec / 引用插件；执行层保证确定性。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:  # 包导入 / 脚本直跑双写法
    from service.data_ingestion.sql_safety import ensure_read_only
    from service.runtime.exceptions import ServiceError
except ImportError:  # pragma: no cover - 兼容直接运行
    from ..data_ingestion.sql_safety import ensure_read_only  # type: ignore
    from ..runtime.exceptions import ServiceError  # type: ignore

# 影响结果语义的结构性版本：改序列化/校验规则时递增，让旧缓存的 view_id 不再命中
DATA_VIEW_VERSION = 1

# 输出错误码（结构化、稳定；MCP/测试都按 code 分支）
SPEC_INVALID = "SPEC_INVALID"
WRITE_STATEMENT_REJECTED = "WRITE_STATEMENT_REJECTED"
UNORDERED_OUTPUT = "UNORDERED_OUTPUT"
PLUGIN_NOT_FOUND = "PLUGIN_NOT_FOUND"
PLUGIN_FORBIDDEN = "PLUGIN_FORBIDDEN"
EXEC_ERROR = "EXEC_ERROR"
SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
EMPTY_RESULT = "EMPTY_RESULT"
ROW_LIMIT_EXCEEDED = "ROW_LIMIT_EXCEEDED"
INPUT_NOT_FOUND = "INPUT_NOT_FOUND"
INPUT_INVALID = "INPUT_INVALID"


class DataViewError(ServiceError):
    """数据视图层结构化错误。

    Args:
        message: 人类可读原因（含可行动的 hint 信息）。
        code: 固定枚举错误码；测试与 MCP 按它分支。
    """

    def __init__(self, message: str, code: str = SPEC_INVALID):
        super().__init__(message)
        self.code = code


@dataclass
class ViewSpec:
    """一条声明式数据变换。

    Args:
        kind: ``sql``（只读 SELECT/WITH）或 ``plugin``（已注册纯函数引用）。
        sql: kind=sql 时的完整查询语句。
        plugin: kind=plugin 时的插件名（如 ``kline_resample``）。
        params: 插件参数（SQL 场景留空；未来可扩展为查询绑定参数）。
        inputs: 输入表名列表（执行时按名注册 DataFrame；sql 支持多表 join，
            plugin 只允许 1 个输入）。
        allow_unordered: SQL 未写 ``ORDER BY`` 时是否放行；默认 False，
            保证输出顺序稳定。
        allow_empty: 输出 0 行时是否放行；默认 False（空结果通常是错误信号）。
        title: 可选一句话描述，只进 manifest 摘要，不参与 hash 之外的语义。
    """

    kind: str
    sql: str | None = None
    plugin: str | None = None
    plugin_version: int | None = None
    params: dict[str, Any] = field(default_factory=dict)
    inputs: list[str] = field(default_factory=list)
    allow_unordered: bool = False
    allow_empty: bool = False
    title: str = ""


def _clean(text: str) -> str:
    """去掉去重空白，供规范化序列化使用。"""
    return " ".join(str(text or "").split())


def payload_of(spec: ViewSpec) -> dict[str, Any]:
    """ViewSpec 的规范化 dict（参与 hash 的字段确定顺序）。

    参数按键排序后再序列化，保证 ``{"a":1,"b":2}`` 与 ``{"b":2,"a":1}`` 同 hash。
    """
    return {
        "version": DATA_VIEW_VERSION,
        "kind": _clean(spec.kind),
        "sql": _clean(spec.sql) if spec.sql else None,
        "plugin": _clean(spec.plugin) if spec.plugin else None,
        "plugin_version": int(spec.plugin_version) if spec.plugin_version else None,
        "params": _sort_params(spec.params),
        "inputs": [_clean(x) for x in spec.inputs],
        "allow_unordered": bool(spec.allow_unordered),
        "allow_empty": bool(spec.allow_empty),
    }


def _sort_params(params: dict[str, Any]) -> dict[str, Any]:
    """递归地按键排序 params，保证 JSON 序列化顺序无关。"""
    if isinstance(params, dict):
        return {k: _sort_params(v) for k, v in sorted(params.items(), key=lambda kv: kv[0])}
    if isinstance(params, list):
        return [_sort_params(v) for v in params]
    return params


def _canonical_json(payload: dict[str, Any]) -> str:
    """payload 的确定性 JSON 文本（ensure_ascii=False，仅 ASCII 无法表示中文时保留原文）。"""
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def spec_hash(spec: ViewSpec) -> str:
    """spec 的 sha256（hex）；同语义 spec 必得同 hash。"""
    return hashlib.sha256(_canonical_json(payload_of(spec)).encode("utf-8")).hexdigest()


def view_id(spec: ViewSpec, input_fingerprints: dict[str, str]) -> str:
    """view 的内容寻址 id：``vw_<hash16>``。

    Args:
        spec: 数据变换定义。
        input_fingerprints: 表名 -> 输入数据指纹（由引擎计算，见 ``engine``）。
            缺少 spec 声明的输入名时抛 ``INPUT_NOT_FOUND``。

    Returns:
        str: ``vw_`` 前缀 + 16 位 hex，用作缓存文件名与 series 溯源。
    """
    missing = [name for name in spec.inputs if name not in input_fingerprints]
    if missing:
        raise DataViewError(
            f"缺少输入数据指纹: {missing}；请先在引擎里注册全部输入表",
            INPUT_NOT_FOUND,
        )
    parts = [spec_hash(spec)]
    parts.extend(input_fingerprints[name] for name in spec.inputs)
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return f"vw_{digest[:16]}"


def validate_spec(spec: ViewSpec) -> None:
    """静态校验 ViewSpec（不执行、不访问数据）。

    Raises:
        DataViewError: kind 未知 / SQL 为空或多语句含写操作（``WRITE_STATEMENT_REJECTED``）/
            输出未声明稳定排序（``UNORDERED_OUTPUT``）/ 插件场景非法。
    """
    if spec.kind == "sql":
        sql = _clean(spec.sql)
        if not sql:
            raise DataViewError("SQL 不能为空", SPEC_INVALID)
        try:
            ensure_read_only(sql)
        except ValueError as e:
            raise DataViewError(str(e), WRITE_STATEMENT_REJECTED) from e
        if not spec.allow_unordered and "order by" not in sql.lower():
            raise DataViewError(
                "SQL 输出必须稳定排序：请写 ORDER BY，或显式声明 allow_unordered=True",
                UNORDERED_OUTPUT,
            )
        if not spec.inputs:
            raise DataViewError("SQL 场景至少要声明 1 个输入表名", SPEC_INVALID)
        return

    if spec.kind == "plugin":
        if not _clean(spec.plugin):
            raise DataViewError("plugin name 不能为空", SPEC_INVALID)
        if len(spec.inputs) != 1:
            raise DataViewError("plugin 场景只支持 1 个输入表，SQL 场景才支持多表", SPEC_INVALID)
        try:
            _sort_params(spec.params)  # params 必须可 JSON 序列化
            _canonical_json({"params": _sort_params(spec.params)})
        except (TypeError, ValueError) as e:
            raise DataViewError(f"params 必须可 JSON 序列化: {e}", SPEC_INVALID) from e
        return

    raise DataViewError(f"未知 spec kind: {spec.kind}（只支持 sql / plugin）", SPEC_INVALID)


def spec_summary(spec: ViewSpec) -> str:
    """给 manifest / agent 的单行摘要（截断长 SQL，避免上下文膨胀）。"""
    if spec.kind == "sql":
        text = _clean(spec.sql) or ""
    else:
        params = json.dumps(_sort_params(spec.params), ensure_ascii=True, separators=(",", ":"))
        text = f"{spec.plugin}({params})"
    if len(text) > 160:
        text = text[:157] + "..."
    extra = " [无排序]" if spec.kind == "sql" and spec.allow_unordered else ""
    return text + extra


def plugin_dir_for_seed() -> Path:
    """默认插件目录（``plugins/data_view``；目录可不存在，注册表为空也成立）。"""
    return Path(__file__).resolve().parents[2] / "plugins" / "data_view"
