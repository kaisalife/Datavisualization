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
    """把外部数据源转成 VizDataset。内部分三阶段：
    - fetch: 允许调用 LLM/沙箱，处理模糊需求（脏活集中在此）
    - clean: 可选，LLM 生成 YAML 规则 -> 规则引擎执行 -> AI 验证 -> 循环
    - normalize: 纯函数，把 RawDataBundle 组装成 VizDataset
    """

    # ─── 清洗配置（子类可覆盖）───
    needs_cleaning: bool = True
    """是否需要数据清洗阶段。"""

    auto_skip_if_clean: bool = True
    """数据质量检查通过时自动跳过清洗。"""

    async def adapt(self, engine: "QueryEngine | None" = None) -> VizDataset:
        """完整流程 = fetch + clean(可选) + normalize。"""
        self.validate()
        raw = await self.fetch(engine)

        # clean 阶段（可选）：质量检查 -> 决策 -> 清洗
        if self.needs_cleaning and engine is not None:
            raw = await self._try_clean(raw, engine)

        dataset = self.normalize(raw)
        # 强制填充 descriptor（如果子类没在 normalize 里填的话）
        if dataset.descriptor is None:
            dataset.descriptor = self.descriptor()
        return dataset

    async def _try_clean(self, raw: RawDataBundle, engine: "QueryEngine") -> RawDataBundle:
        """尝试清洗数据。

        1. 对每个 tabular_file 生成预览 + 质量检查
        2. 数据够干净且 auto_skip_if_clean -> 跳过
        3. 需要清洗 -> CleaningPipeline（3次循环 + fallback）
        """
        import pandas as pd

        from service.viz_data.cleaning.pipeline import CleaningPipeline
        from service.viz_data.cleaning.preview import (
            DataQualityChecker,
            generate_preview,
        )

        if not raw.tabular_files:
            return raw

        # 对每个 tabular_file 检查质量
        all_issues = []
        for tabular_file in raw.tabular_files:
            try:
                df = pd.read_parquet(tabular_file["path"])
                preview = generate_preview(df, tabular_file["name"])
                quality = DataQualityChecker.check(preview)
                if not quality.is_clean:
                    all_issues.extend(quality.issues)
            except Exception as e:
                print(f"  ⚠️ 质量检查失败 [{tabular_file['name']}]: {e}")

        # 数据够干净
        if not all_issues and self.auto_skip_if_clean:
            raw.fetch_context["cleaning_skipped"] = True
            raw.fetch_context["quality"] = "clean"
            return raw

        # 执行清洗
        if all_issues:
            print(f"  🧹 数据质量检查发现 {len(all_issues)} 个问题，启动清洗...")
            pipeline = CleaningPipeline(raw, engine, all_issues)
            return await pipeline.run()

        # 没有 issues 但 auto_skip_if_clean=False（如 PDF 总是清洗）
        # 目前先跳过，后续可以强制走 LLM 检查
        raw.fetch_context["cleaning_skipped"] = True
        raw.fetch_context["quality"] = "clean"
        return raw

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
