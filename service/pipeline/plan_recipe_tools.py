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
from service.data_ingestion.series.shape import format_shape_summary
from service.pipeline.chart_recommend import recommend_chart_types


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
        lines = []
        for s in series:
            advice = recommend_chart_types(s, load_if_missing=False)
            shape = format_shape_summary(advice.get("shape"))
            shape_text = f"；{shape}" if shape else ""
            suggested = "/".join(advice.get("recommended", []))
            alternatives = "/".join(advice.get("alternatives", []))
            advice_text = f"；建议 {suggested}" if suggested else ""
            if alternatives:
                advice_text += f"（备选 {alternatives}）"
            lines.append(
                f"{s.series_id} [{s.axis_kind}{shape_text}]: {s.description}"
                f"（行标签={s.row_label_column}, 列标签={s.column_label_columns}）"
                f"{advice_text}"
            )
        return ToolOutput(success=True, output=f"可用数据系列 {len(series)} 条:\n" + "\n".join(lines))


class LoadSkillInput(BaseModel):
    """load_skill 输入。"""

    name: str = Field(..., description="技能名，如 high-frequency-timeseries")


class LoadSkillTool(Tool):
    """按名称加载技能全文（渐进式披露，避免主 prompt 塞满特殊场景规则）。"""

    def __init__(self, auto_confirm: bool = True):
        super().__init__(
            name="load_skill",
            description="加载某个技能的完整指南。先查看规划 prompt 中的技能索引，"
                        "只在数据/需求匹配时调用；普通图表不需要加载。",
            args_schema=LoadSkillInput,
            is_read_only=True, is_destructive=False, is_concurrency_safe=True,
            auto_confirm=auto_confirm,
        )

    def check_permissions(self, ctx: ToolContext) -> Decision:
        return Decision(PermissionDecision.ALLOW)

    async def call(self, input_data: Dict[str, Any], ctx: ToolContext) -> ToolOutput:
        from service.skills import get_skill_registry

        name = str(input_data.get("name", "")).strip()
        registry = get_skill_registry()
        skill = registry.get(name)
        if skill is None:
            names = ", ".join(s.name for s in registry.skills) or "(无)"
            return ToolOutput(
                success=False,
                error=f"技能不存在: {name}；可用技能: {names}",
            )
        return ToolOutput(
            success=True,
            output=f"# {skill.title}\n\n{skill.body}",
        )


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

        advice = recommend_chart_types(series, load_if_missing=True)
        shape = advice.get("shape") or {}
        examples = shape.get("row_label_examples") or []
        return ToolOutput(
            success=True,
            output=(
                f"{series.series_id} [{series.axis_kind}]\n"
                f"说明: {series.description}\n"
                f"数据形态: {format_shape_summary(shape) or '(未知)'}\n"
                f"行标签列: {series.row_label_column}\n列标签列: {series.column_label_columns}\n"
                f"行标签示例: {examples}\n"
                f"建议图表: {'/'.join(advice.get('recommended', [])) or '(无)'}"
                f"（{advice.get('reason', '')}）\n"
                f"真实样例(前5行): {preview}"
            ),
        )