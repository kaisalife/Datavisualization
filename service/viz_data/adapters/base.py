"""VizDataAdapter 抽象基类。

所有数据源 Adapter 继承本类，实现两阶段：
- fetch: 允许调用 LLM/沙箱，处理模糊需求（脏活集中在此）
- normalize: 纯函数，把 RawDataBundle 组装成 VizDataset

契约说明：
- normalize 阶段禁止发起新的 IO（读取 raw 里已落盘的 parquet 是"解引用"，允许）
- normalize 阶段禁止调用 LLM / QueryEngine
- normalize 阶段禁止修改 raw
违反视为 bug，会破坏"防腐层"语义。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from service.viz_data.capabilities import AdapterCapabilities
from service.viz_data.schema import RawDataBundle, VizDataset
from service.viz_data.source_descriptor import SourceDescriptor

if TYPE_CHECKING:
    from service.query_engine import QueryEngine


class AdapterError(Exception):
    """Adapter 参数或流程错误。"""


class VizDataAdapter(ABC):
    """把外部数据源转成 VizDataset。内部分两阶段。"""

    async def adapt(self, engine: "QueryEngine | None" = None) -> VizDataset:
        """完整流程 = fetch + normalize。"""
        self.validate()
        raw = await self.fetch(engine)
        dataset = self.normalize(raw)
        # 强制填充 descriptor（如果子类没在 normalize 里填的话）
        if dataset.descriptor is None:
            dataset.descriptor = self.descriptor()
        return dataset

    @abstractmethod
    async def fetch(self, engine: "QueryEngine | None") -> RawDataBundle:
        """Phase 1: Agent 参与，处理模糊需求，探索数据源，拉取具体数据。"""

    @abstractmethod
    def normalize(self, raw: RawDataBundle) -> VizDataset:
        """Phase 2: 纯函数，把原始数据封装成 VizDataset。

        契约（强约束，违反视为 bug）：
        - 禁止发起新 IO：raw.tabular_files 里的路径读取属于"解引用"，允许
        - 禁止调用 LLM / QueryEngine（如需要，请在 fetch 阶段完成）
        - 禁止修改传入的 raw
        - 应能被多次调用产生相同结果（幂等）
        """

    @abstractmethod
    def source_kind(self) -> str:
        """标识：'file' | 'database' | 'code' | ..."""

    def validate(self) -> None:
        """入参校验，默认无操作。子类可覆盖。"""
        return None

    # -------- 端口：能力声明 --------

    def capabilities(self) -> AdapterCapabilities:
        """声明本 Adapter 的能力位。

        默认返回一个保守值，子类应根据自身特性覆盖：
        - 需要 LLM 的 Adapter 覆盖 needs_llm=True
        - 支持多资源产出的覆盖 supports_multi_query=True
        """
        return AdapterCapabilities(needs_llm=False, supports_multi_query=False)

    # -------- 端口：数据源描述 --------

    def descriptor(self) -> SourceDescriptor:
        """脱敏后的数据源描述。子类应覆盖以提供有意义的 label / logical_id。"""
        kind = self.source_kind()
        # 兜底：只保证 kind 合法，label/logical_id 用类名
        cls_name = type(self).__name__
        return SourceDescriptor(
            kind=kind if kind in ("file", "database", "code") else "code",
            label=cls_name,
            logical_id=cls_name.lower(),
        )

    # -------- 端口：预览文本 --------

    def preview_text(self, dataset: VizDataset) -> str:
        """派生 human-readable 预览文本。子类可覆盖以支持源特定格式。

        默认实现：基于 tabular 的行数/列名/前 10 行预览。
        """
        if dataset is None or dataset.tabular is None:
            return "(无预览)"

        tab = dataset.tabular
        lines = [
            f"数据来源: {dataset.source_kind} / {dataset.name}",
            f"数据形状: {tab.row_count} 行 × {len(tab.columns)} 列",
            f"列名: {[c.name for c in tab.columns]}",
            "",
            "前 10 行预览:",
        ]
        for row in tab.preview_rows[:10]:
            lines.append("  " + " | ".join(str(v) for v in row))
        return "\n".join(lines)
