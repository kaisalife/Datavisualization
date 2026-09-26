"""阶段 2 计划 agent 工具：series 浏览/获取（v4）。

- list_series:  浏览候选语义 series 索引（来源表 × 系列 × 语义）
- get_series:   取某条 series 的行/列标签 + 描述 + 数据样例
（无 SQL recipe，无需 append variant）
"""
from __future__ import annotations

from typing import Any, Dict

from pydantic import BaseModel, Field

from agent.tools.base import Decision, PermissionDecision, Tool, ToolContext, ToolOutput
from service.data_ingestion.series import load_series_df


class ListSeriesInput(BaseModel):
    """list_series 输入。"""

    source_table: str = Field(default="", description="按来源表名过滤（留空列出全部）")


class ListSeriesTool(Tool):
    """浏览候选语义 series。"""

    def __init__(self, catalog, auto_confirm: bool = True):
        super().__init__(
            name="list_series",
            description="列出可用数据系列（series 索引）：来源表 × 系列ID × 语义类型 × 说明。"
                        "规划前先浏览，据此为每个 plan 选择数据系列。",
            args_schema=ListSeriesInput,
            is_read_only=True, is_destructive=False, is_concurrency_safe=True,
            auto_confirm=auto_confirm,
        )
        self._catalog = catalog

    def check_permissions(self, ctx: ToolContext) -> Decision:
        return Decision(PermissionDecision.ALLOW)

    async def call(self, input_data: Dict[str, Any], ctx: ToolContext) -> ToolOutput:
        table = str(input_data.get("source_table", ""))
        if table:
            series = self._catalog.for_table(table)
        else:
            series = self._catalog.series
        if not series:
            return ToolOutput(success=False, error="series 目录为空或该来源无系列")
        lines = [
            f"{s.series_id} [{s.axis_kind}]: {s.description}（行标签={s.row_label_column}, 列标签={s.column_label_columns}）"
            for s in series
        ]
        return ToolOutput(success=True, output=f"可用数据系列 {len(series)} 条:\n" + "\n".join(lines))


class GetSeriesInput(BaseModel):
    """get_series 输入。"""

    series_id: str = Field(..., description="系列 ID（如 年度数据.城镇居民人均可支配收入）")


class GetSeriesTool(Tool):
    """取某条 series 的标签/语义与数据样例。"""

    def __init__(self, catalog, auto_confirm: bool = True):
        super().__init__(
            name="get_series",
            description="取某条语义 series 的行/列标签、说明与真实数据样例。提交 plan 前确认数据形状。",
            args_schema=GetSeriesInput,
            is_read_only=True, is_destructive=False, is_concurrency_safe=True,
            auto_confirm=auto_confirm,
        )
        self._catalog = catalog

    def check_permissions(self, ctx: ToolContext) -> Decision:
        return Decision(PermissionDecision.ALLOW)

    async def call(self, input_data: Dict[str, Any], ctx: ToolContext) -> ToolOutput:
        series_id = str(input_data.get("series_id", ""))
        series = self._catalog.by_id(series_id)
        if series is None:
            return ToolOutput(success=False, error=f"series 不存在: {series_id}")
        try:
            df = load_series_df(series).head(5)
            preview = df.to_dict(orient="records")
        except Exception as e:
            return ToolOutput(success=False, error=f"series 加载失败: {e}")
        return ToolOutput(
            success=True,
            output=(
                f"{series.series_id} [{series.axis_kind}]\n"
                f"说明: {series.description}\n"
                f"行标签列: {series.row_label_column}\n列标签列: {series.column_label_columns}\n"
                f"真实样例(前5行): {preview}"
            ),
        )