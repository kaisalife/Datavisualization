"""数据视图执行器：把 ViewSpec 确定性地算成 DataFrame。

职责边界：执行、校验输出、计算指纹与 view_id；**不落盘**——物化走
``cache.py``，preview 模式只在内存返回样品。

执行流程（与 docs/数据清洗工具集/03 一致）：

```text
resolve inputs（DataFrame 注册）
  → spec 静态校验（只读 SQL / 已注册插件）
  → 执行（SQLite 内存 / 插件纯函数）
  → 输出校验（行数上限、空结果、插件 OUTPUT_SCHEMA）
  → 返回 view_id + schema（不缓存失败结果）
```

引擎默认 SQLite（内置，零新增依赖）；换后端属于 P2，对 ViewSpec 透明。
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from service.observability import get_logger

try:  # 包导入 / 脚本直跑双写法
    from spec import (
        DATA_VIEW_VERSION,
        EMPTY_RESULT,
        INPUT_INVALID,
        INPUT_NOT_FOUND,
        EXEC_ERROR,
        PLUGIN_NOT_FOUND,
        ROW_LIMIT_EXCEEDED,
        SCHEMA_MISMATCH,
        DataViewError,
        ViewSpec,
        validate_spec,
        view_id as compute_view_id,
    )
    from registry import PluginRegistry, get_default_registry
except ImportError:  # pragma: no cover - 兼容直接运行
    from .spec import (  # type: ignore
        DATA_VIEW_VERSION,
        EMPTY_RESULT,
        INPUT_INVALID,
        INPUT_NOT_FOUND,
        EXEC_ERROR,
        PLUGIN_NOT_FOUND,
        ROW_LIMIT_EXCEEDED,
        SCHEMA_MISMATCH,
        DataViewError,
        ViewSpec,
        validate_spec,
        view_id as compute_view_id,
    )
    from .registry import PluginRegistry, get_default_registry  # type: ignore

logger = get_logger(__name__)

# 默认输出行数上限：超出直接拒绝并提示加 LIMIT（防资源耗尽）
DEFAULT_MAX_ROWS = 2_000_000

# 输入表名约束：SQL 里的表名就是这里注册的名字，必须安全
_TABLE_NAME_ALLOWED = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")


@dataclass
class ViewSchemaColumn:
    """输出 schema 的单列描述。"""

    name: str
    dtype: str


@dataclass
class DataViewResult:
    """一次执行的产物（不关心后续是否物化）。

    Args:
        view_id: 内容寻址 id（``vw_<hex16>``）。
        data: 输出 DataFrame（索引已重置为 0..n-1）。
        schema: 列名 + dtype 描述。
        inputs_fingerprints: 参与计算 view_id 的输入指纹。
        plugin_version: 插件场景记录实际使用的版本（审计用）。
        extra: manifest 追加字段（如耗时）。
    """

    view_id: str
    data: pd.DataFrame
    schema: list[ViewSchemaColumn] = field(default_factory=list)
    inputs_fingerprints: dict[str, str] = field(default_factory=dict)
    plugin_version: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def rows(self) -> int:
        """输出行数。"""
        return int(len(self.data))


def fingerprint_dataframe(df: pd.DataFrame) -> str:
    """DataFrame 的确定性指纹（hex）。

    用 pandas 自带的行/列哈希（同 pandas 版本内跨进程稳定），
    覆盖数据值、列名与 dtype；索引参与哈希，保证同一数据重排后指纹不变、
    不同数据必得新指纹。文件表格在接入层已按内容寻址，这里覆盖内存直传场景。
    """
    import hashlib

    digest = hashlib.sha256()
    digest.update("|".join(df.columns.astype(str)).encode("utf-8"))
    digest.update("|".join(str(x) for x in df.dtypes.astype(str)).encode("utf-8"))
    row_hash = pd.util.hash_pandas_object(df, index=True).to_numpy()
    digest.update(row_hash.tobytes())
    return digest.hexdigest()[:32]


class DataViewEngine:
    """执行 ViewSpec。实例无状态（可并发复用），状态全在视图产物里。"""

    def __init__(
        self,
        registry: PluginRegistry | None = None,
        max_rows: int = DEFAULT_MAX_ROWS,
    ) -> None:
        self._registry = registry
        self._max_rows = int(max_rows)

    # ---- 公共入口 ----
    def execute(
        self,
        spec: ViewSpec,
        inputs: dict[str, pd.DataFrame],
        *,
        mode: str = "preview",
        datasets_dir: str | None = None,
        registry: PluginRegistry | None = None,
    ) -> DataViewResult:
        """执行一条 ViewSpec。

        Args:
            spec: 变换定义。
            inputs: 表名 -> DataFrame；含名称校验与覆盖式注册。
            mode: ``preview`` 只在内存执行；``materialize`` 额外落盘到
                ``datasets_dir``（物化见 ``cache.py``）。
            datasets_dir: mode=materialize 时必填（输出写入该会话目录下的 views/）。
            registry: 覆盖默认插件注册表（测试用）。

        Returns:
            DataViewResult: view_id + 输出 DataFrame + schema。

        Raises:
            DataViewError: 任何阶段失败（错误码见 ``spec`` 模块常量）；失败绝不缓存。
        """
        validate_spec(spec)
        fingerprints: dict[str, str] = {}
        for name in spec.inputs:
            frame = inputs.get(name)
            if frame is None:
                raise DataViewError(f"缺少输入表: {name}", INPUT_NOT_FOUND)
            if not isinstance(frame, pd.DataFrame):
                raise DataViewError(f"输入 {name} 必须是 pandas DataFrame", INPUT_INVALID)
            fingerprints[name] = fingerprint_dataframe(frame)

        registry = registry or self._registry or get_default_registry()
        if spec.kind == "sql":
            data, plugin_version = self._exec_sql(spec, inputs), None
        else:
            data, plugin_version = self._exec_plugin(spec, inputs, registry)

        result = self._validate_output(spec, data, fingerprints, plugin_version)
        if mode == "materialize":
            if not datasets_dir:
                raise DataViewError("materialize 模式需要 datasets_dir", INPUT_INVALID)
            # 局部导入防循环依赖
            try:
                from cache import materialize_view
            except ImportError:
                from .cache import materialize_view  # type: ignore
            result.extra["parquet_path"] = materialize_view(
                spec=spec, result=result, datasets_dir=datasets_dir, registry=registry
            )
            result.extra["materialized"] = True
        elif mode != "preview":
            raise DataViewError(f"未知 mode: {mode}（只支持 preview / materialize）", INPUT_INVALID)
        return result

    # ---- SQL 执行 ----
    @staticmethod
    def _table_name(name: str) -> str:
        """校验表名（字母/数字/下划线），非法即拒绝。"""
        if not name or any(ch not in _TABLE_NAME_ALLOWED for ch in name):
            raise DataViewError(
                f"输入表名必须由字母/数字/下划线组成: {name!r}", INPUT_INVALID
            )
        return name

    def _exec_sql(self, spec: ViewSpec, inputs: dict[str, pd.DataFrame]) -> pd.DataFrame:
        """把全部输入注册进 SQLite 内存库后执行 spec.sql。

        SQLite 对中文列名/值宽容，聚合与窗口能力足够覆盖清洗类变换；
        结果顺序由 spec 的 ORDER BY 保证（未声明排序的在 ``validate_spec`` 已拒绝）。
        """
        conn = sqlite3.connect(":memory:")
        try:
            for name in spec.inputs:
                table = self._table_name(name)
                try:
                    inputs[name].to_sql(table, conn, if_exists="replace", index=False)
                except Exception as e:  # 数据本身无法入库（混合 dtype 等极端情况）
                    raise DataViewError(
                        f"输入表 {name} 无法注册到 SQLite: {e}", INPUT_INVALID
                    ) from e
            try:
                return pd.read_sql_query(spec.sql, conn, params=spec.params or None)
            except Exception as e:
                raise DataViewError(f"SQL 执行失败: {e}", EXEC_ERROR) from e
        finally:
            conn.close()

    # ---- 插件执行 ----
    @staticmethod
    def _exec_plugin(
        spec: ViewSpec,
        inputs: dict[str, pd.DataFrame],
        registry: PluginRegistry,
    ) -> tuple[pd.DataFrame, int]:
        """执行插件（单输入、纯函数、params 显式透传）。

        Raises:
            DataViewError: 插件未注册 / 执行抛错；失败回答案在错误码里。
        """
        entry = registry.get(spec.plugin, spec.plugin_version)
        df = inputs[spec.inputs[0]]
        try:
            out = entry.apply(df, dict(spec.params))
        except DataViewError:
            raise
        except Exception as e:
            raise DataViewError(f"插件 {entry.name} 执行失败: {e}", EXEC_ERROR) from e
        if not isinstance(out, pd.DataFrame):
            raise DataViewError(f"插件 {entry.name} 未返回 DataFrame", SCHEMA_MISMATCH)
        return out, entry.version

    # ---- 输出校验 ----
    def _validate_output(
        self,
        spec: ViewSpec,
        data: pd.DataFrame,
        fingerprints: dict[str, str],
        plugin_version: int | None,
    ) -> DataViewResult:
        """统一输出校验：行数上限、空结果、插件 schema 声明。"""
        if len(data) > self._max_rows:
            raise DataViewError(
                f"输出 {len(data)} 行超过上限 {self._max_rows}；请在 SQL/插件里加 LIMIT 或聚合",
                ROW_LIMIT_EXCEEDED,
            )
        if len(data) == 0 and not spec.allow_empty:
            raise DataViewError(
                "输出 0 行且未声明 allow_empty=True；请检查筛选/聚合条件", EMPTY_RESULT
            )
        entry = self._registry_plugin(spec) if spec.kind == "plugin" else None
        if entry is not None and entry.schema:
            expected = [c["name"] for c in entry.schema]
            missing = [c for c in expected if c not in data.columns]
            if missing:
                raise DataViewError(
                    f"插件输出缺少声明列: {missing}（声明 {expected}，实际 {list(data.columns)}）",
                    SCHEMA_MISMATCH,
                )
        view_id = compute_view_id(spec, fingerprints)
        schema = [ViewSchemaColumn(name=str(c), dtype=str(d)) for c, d in zip(data.columns, data.dtypes)]
        return DataViewResult(
            view_id=view_id,
            data=data.reset_index(drop=True),
            schema=schema,
            inputs_fingerprints=fingerprints,
            plugin_version=plugin_version,
            extra={"engine_version": DATA_VIEW_VERSION},
        )

    def _registry_plugin(self, spec: ViewSpec):
        """取插件条目用于 schema 校验（缺失时让校验跳过，不二次报错）。"""
        try:
            return (self._registry or get_default_registry()).get(spec.plugin)
        except DataViewError as e:
            if e.code == PLUGIN_NOT_FOUND:
                raise
            return None
