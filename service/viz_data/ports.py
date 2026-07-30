"""viz_data 层的端口协议（Protocol）汇总。

集中声明所有对外契约，作为 Adapter 层的"契约面板"。
用 typing.Protocol 而非 ABC，允许 duck typing 和 Fake/Mock 替身。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Protocol, runtime_checkable

from service.viz_data.capabilities import AdapterCapabilities
from service.viz_data.source_descriptor import SourceDescriptor

if TYPE_CHECKING:
    from service.query_engine import QueryEngine
    from service.viz_data.schema import VizDataset


@runtime_checkable
class VizDataAdapterPort(Protocol):
    """数据源适配器端口。

    任何数据源（文件、数据库、未来的网页/文章）都必须满足此契约，
    才能被 DataSourceRegistry 识别、被 planner/chart_generator 消费。
    """

    async def adapt(self, engine: Optional["QueryEngine"] = None) -> "VizDataset":
        """完整流程 = fetch + normalize，产出 VizDataset。"""
        ...

    def source_kind(self) -> str:
        """标识：'file' | 'database' | 'code' | ..."""
        ...

    def capabilities(self) -> AdapterCapabilities:
        """声明本 Adapter 的能力。"""
        ...

    def descriptor(self) -> SourceDescriptor:
        """脱敏后的数据源描述。"""
        ...


@runtime_checkable
class QueryPlannerPort(Protocol):
    """查询规划器端口。

    职责：把 (数据源 schema + 用户意图) 规划成一批可执行的 Query。
    实现方可以是 LLM、模板、规则引擎等。
    """

    async def plan(
        self,
        *,
        schema_text: str,
        user_prompt: str,
        hint: Optional[str] = None,
        max_queries: int = 1,
    ) -> list["Query"]:
        """生成查询列表。

        Args:
            schema_text: 数据源 schema 的文本描述（LLM 友好格式）
            user_prompt: 用户的自然语言意图
            hint: 可选提示（如指定表名/集合名）
            max_queries: 最多生成几条查询

        Returns:
            Query 列表，长度 1..max_queries
        """
        ...


# 前向引用避免循环：Query 定义在 planning.query_planner
if TYPE_CHECKING:
    from service.viz_data.planning.query_planner import Query


__all__ = [
    "VizDataAdapterPort",
    "QueryPlannerPort",
]
