"""ReadSeriesSampleTool：语义 series 采样查看工具（只读，v4）。

debug agent / 计划 agent 用：查看某个 series 的真实数据结构与取值，
为规划/修复代码提供证据。不再连接 DuckDB，直接从 series .parquet 加载。
"""
from __future__ import annotations

import json
from typing import Any, Dict

from pydantic import BaseModel, Field

from agent.tools.base import Decision, PermissionDecision, Tool, ToolContext, ToolOutput
from service.data_ingestion.series import load_series_df
from service.data_ingestion.series.models import SeriesCatalog


class ReadSeriesSampleInput(BaseModel):
    """ReadSeriesSampleTool 输入。"""

    series_id: str = Field(
        ...,
        description="语义 series ID（如 年度数据.城镇居民人均可支配收入，来自 list_series）",
    )
    limit: int = Field(default=10, description="最多返回行数（默认 10，上限 100）")


class ReadSeriesSampleTool(Tool):
    """只读采样某个语义 series 的真实数据。"""

    def __init__(self, catalog: SeriesCatalog, auto_confirm: bool = True):
        super().__init__(
            name="read_series_sample",
            description="查看某个语义 series 的真实数据（从该 series 的 parquet 只读加载，最多 100 行）。"
                        "用于确认列名/数据分布/取值样例。",
            args_schema=ReadSeriesSampleInput,
            is_read_only=True,
            is_destructive=False,
            is_concurrency_safe=True,
            auto_confirm=auto_confirm,
        )
        self._catalog = catalog

    def check_permissions(self, ctx: ToolContext) -> Decision:
        return Decision(PermissionDecision.ALLOW)

    async def call(self, input_data: Dict[str, Any], ctx: ToolContext) -> ToolOutput:
        try:
            validated = self.validate_input(input_data)
            series_id = validated.series_id
            limit = max(1, min(validated.limit, 100))
        except Exception as e:
            return ToolOutput(success=False, error=f"输入校验失败: {e}")

        series = self._catalog.by_id(series_id)
        if series is None:
            return ToolOutput(success=False, error=f"series 不存在: {series_id}")
        try:
            df = load_series_df(series).head(limit)
        except Exception as e:
            return ToolOutput(success=False, error=f"series 加载失败: {e}")

        return ToolOutput(
            success=True,
            output=(
                f"series: {series_id} [{series.axis_kind}]\n"
                f"行标签列: {series.row_label_column}\n列标签列: {series.column_label_columns}\n"
                f"列: {list(df.columns)}\n行数(上限{limit}): {len(df)}\n"
                f"数据:\n{json.dumps(df.to_dict(orient='records'), ensure_ascii=False, default=str)}"
            ),
        )