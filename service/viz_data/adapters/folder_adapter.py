"""文件夹（zip 压缩包）批量上传 Adapter。

适用场景：
- 用户有一个包含大量 Excel/CSV 的文件夹，打包成 zip 上传
- 不同子目录存放不同时间粒度的数据

核心能力：
- 解压 zip 文件到临时目录
- 递归扫描所有支持的文件（Excel/CSV/JSON/JSONL/PDF）
- 同类型文件自动走 MultiExcelAdapter（Excel/CSV）或其他对应 Adapter
- 可选按文件名前缀分组合并
"""
from __future__ import annotations

import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from service.viz_data.adapters.base import AdapterError, VizDataAdapter
from service.viz_data.capabilities import AdapterCapabilities
from service.viz_data.schema import RawDataBundle, VizDataset
from service.viz_data.source_descriptor import SourceDescriptor
from service.viz_data.storage import new_dataset_dir

if TYPE_CHECKING:
    from service.query_engine import QueryEngine


# 支持的文件后缀
_SUPPORTED_SUFFIXES = {".xlsx", ".xls", ".csv", ".json", ".jsonl", ".pdf"}
# 需要合并的表格类型
_TABULAR_SUFFIXES = {".xlsx", ".xls", ".csv"}


class FolderAdapter(VizDataAdapter):
    """把 zip 压缩包中的数据文件批量转成 VizDataset。

    Args:
        zip_path: zip 文件路径
        group_by_prefix: 是否按文件名前缀分组合并（默认 True）
        prefix_delimiter: 前缀分隔符（默认 "_"，例如 "2024_01_sales.xlsx" 取 "2024_01" 为组）
        flatten: 传给 JSON Adapter 的参数
        dataset_name: 数据集名称（默认取 zip 文件名）
    """

    def __init__(
        self,
        zip_path: str,
        group_by_prefix: bool = True,
        prefix_delimiter: str = "_",
        flatten: bool = True,
        dataset_name: Optional[str] = None,
    ):
        self.zip_path = Path(zip_path)
        self.group_by_prefix = group_by_prefix
        self.prefix_delimiter = prefix_delimiter
        self.flatten = flatten
        self.dataset_name = dataset_name or self.zip_path.stem

    def source_kind(self) -> str:
        return "folder"

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(needs_llm=False, supports_multi_query=True)

    def validate(self) -> None:
        if not self.zip_path.exists():
            raise AdapterError(f"ZIP 文件不存在: {self.zip_path}")
        if self.zip_path.suffix.lower() != ".zip":
            raise AdapterError(f"仅支持 .zip，不支持: {self.zip_path.suffix}")
        # 简单检查是否是有效 zip
        if not zipfile.is_zipfile(self.zip_path):
            raise AdapterError(f"不是有效的 ZIP 文件: {self.zip_path}")

    async def fetch(self, engine: "QueryEngine | None") -> RawDataBundle:
        """Phase 1: 解压 zip -> 扫描文件 -> 按类型分发处理。"""
        dataset_dir = new_dataset_dir()

        # 解压
        extract_dir = dataset_dir / "_extracted"
        extract_dir.mkdir(exist_ok=True)

        with zipfile.ZipFile(self.zip_path, "r") as zf:
            # 过滤掉 macOS 资源文件 / 隐藏文件 / 目录
            valid_files = [
                info for info in zf.infolist()
                if not info.is_dir()
                and not Path(info.filename).name.startswith(".")
                and "__MACOSX" not in info.filename
            ]

            # 只保留支持的后缀
            data_files = [
                info for info in valid_files
                if Path(info.filename).suffix.lower() in _SUPPORTED_SUFFIXES
            ]

            if not data_files:
                raise AdapterError(
                    f"ZIP 包中未发现支持的数据文件（支持: {', '.join(_SUPPORTED_SUFFIXES)}），"
                    f"共扫描到 {len(valid_files)} 个非目录文件"
                )

            zf.extractall(extract_dir, members=[info.filename for info in data_files])

        # 扫描解压后的文件
        extracted_paths = sorted(extract_dir.rglob("*"))
        file_paths = [
            p for p in extracted_paths
            if p.is_file() and p.suffix.lower() in _SUPPORTED_SUFFIXES
        ]

        # 按后缀分组
        by_suffix: dict[str, list[Path]] = {}
        for p in file_paths:
            suffix = p.suffix.lower()
            by_suffix.setdefault(suffix, []).append(p)

        return RawDataBundle(
            dataset_dir=str(dataset_dir),
            meta={
                "source": "folder",
                "original_zip": str(self.zip_path),
                "total_files": len(file_paths),
                "files_by_suffix": {k: len(v) for k, v in by_suffix.items()},
                "group_by_prefix": self.group_by_prefix,
            },
            # tabular_files 在 normalize 阶段生成
            tabular_files=[],
        )

    def normalize(self, raw: RawDataBundle) -> VizDataset:
        """Phase 2: 按类型分发到各 Adapter，合并结果。

        策略：
        - Excel/CSV 走 MultiExcelAdapter 批量合并
        - JSON/JSONL 走 JsonAdapter（每个文件单独一个 related_dataset）
        - PDF 走 PdfAdapter（每个文件单独一个 related_dataset）
        - 文件最多的组作为主表，其余作为 related_datasets
        """
        dataset_dir = Path(raw.dataset_dir)
        extract_dir = dataset_dir / "_extracted"

        # 扫描文件
        file_paths = [
            p for p in extract_dir.rglob("*")
            if p.is_file() and p.suffix.lower() in _SUPPORTED_SUFFIXES
        ]

        if not file_paths:
            raise AdapterError("解压后未发现有效数据文件")

        # 按后缀分组
        by_suffix: dict[str, list[Path]] = {}
        for p in file_paths:
            suffix = p.suffix.lower()
            by_suffix.setdefault(suffix, []).append(p)

        all_datasets: list[VizDataset] = []

        # 处理 Excel/CSV（批量合并）
        tabular_paths = []
        for suffix in _TABULAR_SUFFIXES:
            if suffix in by_suffix:
                tabular_paths.extend(by_suffix[suffix])

        if tabular_paths:
            from service.viz_data.adapters.multi_excel_adapter import MultiExcelAdapter

            multi_adapter = MultiExcelAdapter(
                file_paths=[str(p) for p in tabular_paths],
                add_source_column=True,
            )
            multi_raw = multi_adapter._sync_fetch()
            multi_ds = multi_adapter.normalize(multi_raw)
            all_datasets.append(multi_ds)

        # 处理 JSON/JSONL（每个文件单独处理）
        for suffix in (".json", ".jsonl"):
            if suffix not in by_suffix:
                continue
            from service.viz_data.adapters.json_adapter import JsonAdapter

            for p in by_suffix[suffix]:
                try:
                    json_adapter = JsonAdapter(str(p), flatten=self.flatten)
                    json_raw = json_adapter._sync_fetch()
                    json_ds = json_adapter.normalize(json_raw)
                    all_datasets.append(json_ds)
                except Exception as e:
                    # 某个 JSON 失败不影响整体，记录错误继续
                    import logging
                    logging.warning(f"FolderAdapter: 处理 {p.name} 失败: {e}")

        # 处理 PDF（每个文件单独处理）
        if ".pdf" in by_suffix:
            from service.viz_data.adapters.pdf_adapter import PdfAdapter

            for p in by_suffix[".pdf"]:
                try:
                    pdf_adapter = PdfAdapter(str(p))
                    pdf_raw = pdf_adapter._sync_fetch()
                    pdf_ds = pdf_adapter.normalize(pdf_raw)
                    all_datasets.append(pdf_ds)
                except Exception as e:
                    import logging
                    logging.warning(f"FolderAdapter: 处理 {p.name} 失败: {e}")

        if not all_datasets:
            raise AdapterError("所有文件处理失败，未生成有效数据集")

        # 确定主表：行数最多的那个
        primary = max(all_datasets, key=lambda d: (
            d.tabular.row_count if d.tabular else 0
        ))
        related = [d for d in all_datasets if d is not primary]

        # 更新 descriptor
        primary.descriptor = SourceDescriptor(
            kind="folder",
            label=f"📁 {self.dataset_name} ({len(all_datasets)} 个数据集)",
            logical_id=f"folder_{self.dataset_name}",
            extra={
                "original_zip": str(self.zip_path),
                "total_datasets": len(all_datasets),
                "related_count": len(related),
            },
        )

        # 将 related 加到主表的 related_datasets 中
        primary.related_datasets.extend(related)

        return primary

    def _sync_fetch(self) -> RawDataBundle:
        """同步版本 fetch（供 normalize 内部调用，避免 async 嵌套问题）。"""
        import asyncio

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.fetch(None))
        finally:
            loop.close()
