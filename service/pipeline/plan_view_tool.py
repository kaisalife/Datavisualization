"""阶段 2 规划 agent 工具：数据视图（describe_dataset / run_view）。

与 MCP 暴露面（``agent_tools/tool_data_view.py``）同名同契约，但在进程内执行：
``run_view`` materialize 后把产物注册进当前会话的 series 目录，
agent 随后用 ``create_plan`` 引用新 series_id——plan schema 不变（仍只认 series_id）。

- 表别名：raw 表 ``table_<i>``、series 产物 ``series_<i>``（describe_dataset 给映射）；
- ``preview`` 只回内存样品；``materialize`` 落盘 ``views/`` 并写 manifest；
- 未提出加工需求时 agent 不调用本工具，默认路径零改动（自查标准见 05）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pandas as pd
from pydantic import BaseModel, Field

from agent.tools.base import Decision, PermissionDecision, Tool, ToolContext, ToolOutput
from service.observability import get_logger

try:  # 包导入 / 脚本直跑双写法
    from service.data_view.session import describe_dataset, run_view
    from service.data_view.spec import DataViewError, ViewSpec, spec_from_dict, spec_summary
except ImportError:  # pragma: no cover
    from service.data_view.session import describe_dataset, run_view  # type: ignore
    from service.data_view.spec import (  # type: ignore
        DataViewError,
        ViewSpec,
        spec_from_dict,
        spec_summary,
    )

logger = get_logger(__name__)

# run_view 返回样品行数（给 agent 判断视角是否正确）
_TOOL_SAMPLE_ROWS = 5


class DescribeDatasetTool(Tool):
    """列出当前数据会话的可查询表（SQL 别名映射）与已有 view。"""

    def __init__(self, catalog_datasets_dir: str, auto_confirm: bool = True):
        super().__init__(
            name="describe_dataset",
            description=(
                "列出当前数据集可查询的表及其列（raw 明细表 table_0…、identity series table series_<i>…）"
                "与已物化的派生 view 列表。写 SQL 前先调用它拿表别名。只读，无副作用。"
            ),
            args_schema=None,
            is_read_only=True, is_destructive=False, is_concurrency_safe=True,
            auto_confirm=auto_confirm,
        )
        self._datasets_dir = str(catalog_datasets_dir or "")

    def check_permissions(self, ctx: ToolContext) -> Decision:
        return Decision(PermissionDecision.ALLOW)

    async def call(self, input_data: Dict[str, Any], ctx: ToolContext) -> ToolOutput:
        datasets_dir = Path(self._datasets_dir)
        dataset_id = datasets_dir.name
        if not dataset_id:
            return ToolOutput(success=False, error="当前会话没有数据目录，无法查询")
        try:
            info = describe_dataset(
                dataset_id, datasets_root=datasets_dir.parent
            )
        except DataViewError as e:
            return ToolOutput(success=False, error=f"describe_dataset [{e.code}]: {e}")
        except Exception as e:
            return ToolOutput(success=False, error=f"describe_dataset 失败: {e}")
        tables = []
        for t in info["tables"]:
            columns = ", ".join(f"{c['name']}({c['dtype']})" for c in t["columns"])
            tables.append(
                f"{t['alias']}: {t['name']} [{t['origin']}] {t['rows']} 行；列: {columns}\n"
                f"  样例: {t['sample']}"
            )
        views = [
            f"  {v['view_id']}: {v.get('spec_summary', '')}（{v.get('rows')} 行）"
            for v in info["views"]
        ]
        text = (
            f"可查询表 {len(tables)} 张:\n" + "\n".join(tables)
            + ("\n已有派生 view:\n" + "\n".join(views) if views else "\n（尚无派生 view）")
            + "\n\n提示: run_view 的 SQL 里直接用 table_N / series_N 别名引用上述表，"
              "输出必须 ORDER BY 稳定排序。"
        )
        return ToolOutput(success=True, output=text)


class RunViewInput(BaseModel):
    """run_view 输入。"""

    spec: dict = Field(
        ...,
        description=(
            "ViewSpec JSON：{kind:'sql', inputs:['table_0'], sql:'select ... order by ...'}；"
            "或 {kind:'plugin', plugin:'名称', plugin_version:N, inputs:[...], params:{}}"
        ),
    )
    mode: str = Field(
        default="materialize",
        description="materialize=物化并注册为系列（可被 plan 引用）；preview=只回内存样例",
    )


class RunViewTool(Tool):
    """执行一条 ViewSpec；materialize 时把产物注册成新的语义 series。"""

    def __init__(self, state, auto_confirm: bool = True):
        super().__init__(
            name="run_view",
            description=(
                "对当前数据集跑一条确定性变换（SQL 聚合/透视/Top-N），产出新的数据系列。"
                "当现有 series 没有用户要的视角（如明细行需要按月合计）时使用："
                "先用 describe_dataset 确认表别名，再用本工具物化，然后 create_plan 引用返回的 series_id。"
            ),
            args_schema=RunViewInput,
            is_read_only=False, is_destructive=False, is_concurrency_safe=False,
            auto_confirm=auto_confirm,
        )
        self._state = state

    def check_permissions(self, ctx: ToolContext) -> Decision:
        return Decision(PermissionDecision.ALLOW)

    async def call(self, input_data: Dict[str, Any], ctx: ToolContext) -> ToolOutput:
        spec_data = input_data.get("spec")
        mode = str(input_data.get("mode") or "materialize").strip().lower()
        if mode not in ("preview", "materialize"):
            return ToolOutput(success=False, error=f"mode 只支持 preview / materialize（得到 {mode}）")
        datasets_dir = Path(str(self._state.catalog.datasets_dir or ""))
        dataset_id = datasets_dir.name
        if not dataset_id:
            return ToolOutput(success=False, error="当前会话没有数据目录，无法执行 run_view")

        try:
            spec = spec_from_dict(spec_data)
        except DataViewError as e:
            return ToolOutput(success=False, error=f"run_view [{e.code}]: {e}")

        try:
            payload = run_view(dataset_id, spec_data, mode=mode, datasets_root=datasets_dir.parent)
        except DataViewError as e:
            return ToolOutput(success=False, error=f"run_view [{e.code}]: {e}")
        except Exception as e:
            return ToolOutput(success=False, error=f"run_view 失败: {type(e).__name__}: {e}")

        if mode == "preview":
            return ToolOutput(
                success=True,
                output=(
                    f"view {payload['view_id']}（preview，未落盘）\n"
                    f"spec: {payload['spec_summary']}\n"
                    f"行数: {payload['rows']}；schema: {payload['schema']}\n"
                    f"样例: {payload['sample']}\n"
                    "如需把该视角注册为系列供 plan 引用，再用 mode=materialize 执行一次。"
                ),
            )

        # materialize：产物挂为 series（identity 之后的第二类视图系列）
        try:
            series_list = register_view_series(self._state.catalog, payload, spec)
        except Exception as e:
            logger.warning("视图系列注册失败", view_id=payload["view_id"], error=str(e))
            series_list = []
        created = "\n".join(
            f"  {s.series_id} [{s.axis_kind}]: {s.description}" for s in series_list
        )
        if not created:
            created = "  （系列注册被跳过，产物仍是 views 目录里的 parquet）"
        answer = (
            f"view {payload['view_id']} 已物化（{payload['rows']} 行，"
            f"{'缓存命中' if payload.get('cached') else '新物化'}）\n"
            f"spec: {payload['spec_summary']}\n"
            f"schema: {payload['schema']}\n"
            f"样例: {payload['sample']}\n"
            f"新增/对应系列:\n{created}\n"
            "用 create_plan 引用上述 series_id（与普通 series 一致，plan 会多一条数据系列）。"
        )
        return ToolOutput(success=True, output=answer)


def register_view_series(catalog, view_payload: dict, spec: ViewSpec) -> list:
    """把物化视图产出的 DataFrame 按接入层同一套启发式注册为语义系列。

    沿用 split_raw_table（deterministic，与 identity series 同一套语义字段），
    每条注册的 extra_semantics 里带 view 溯源；manifest 同步重写。

    Args:
        catalog: 当前会话的 SeriesCatalog（就地追加）。
        view_payload: `run_view(materialize)` 的返回 dict（含 view_id / parquet_path）。
        spec: 对应 ViewSpec（摘要进 extra_semantics）。

    Returns:
        新注册的 SemanticSeries 列表（物化缓存命中时 repr 已注册的现有系列）。
    """
    from service.data_ingestion.series.models import SemanticSeries
    from service.data_ingestion.series.shape import compute_series_shape
    from service.data_ingestion.series.splitter import (
        _safe_filename,
        _sanitize_series_name,
        split_raw_table,
        write_manifest,
    )

    session_dir = Path(catalog.datasets_dir)
    view_id = str(view_payload["view_id"])

    # 重跑同一 spec → 同 view_id：映射已注册的现有系列，不产生重复
    already = [
        s for s in catalog.series
        if (s.extra_semantics or {}).get("view", {}).get("view_id") == view_id
    ]
    if already:
        return already

    df = pd.read_parquet(view_payload["parquet_path"])
    table_name = _sanitize_series_name(spec.title or f"视图{view_id[:10]}")
    existing = {s.series_id for s in catalog.series}

    registered: list = []
    for item in split_raw_table(df, table_name):
        base = _safe_filename(table_name)
        seg = _safe_filename(item["name"])
        series_id = f"{base}.{seg}"
        n = 1
        while series_id in existing:
            series_id = f"{base}.{seg}_{n}"
            n += 1
        existing.add(series_id)

        sub_df = item["df"].reset_index(drop=True)
        data_path = session_dir / f"{series_id}.parquet"
        sub_df.to_parquet(data_path, index=False)
        series = SemanticSeries(
            series_id=series_id,
            name=_sanitize_series_name(item["name"]),
            axis_kind=item["axis_kind"],
            row_label_column=item["row_label_column"],
            column_label_columns=item["column_label_columns"],
            data_path=str(data_path.as_posix()),
            source_table=table_name,
            description=item["description"],
            extra_semantics={
                "shape": compute_series_shape(
                    sub_df, item["axis_kind"], item["row_label_column"],
                    item["column_label_columns"],
                ),
                "origin": "view",
                "source_kind": "derived",
                "source_path": f"views/{view_id}.parquet",
                "view": {
                    "view_id": view_id,
                    "kind": spec.kind,
                    "spec_summary": spec_summary(spec),
                },
            },
            dtype_info={c: str(t) for c, t in sub_df.dtypes.items()},
        )
        registered.append(series)
        catalog.series.append(series)

    if registered:
        write_manifest(catalog, session_dir)
    return registered
