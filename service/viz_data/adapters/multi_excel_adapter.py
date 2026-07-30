"""多 Excel / CSV 智能合并 Adapter。

解决场景：运营每周收 10 个区域经理的 Excel 报表、投后每月收 20 家公司财务表、
HR 收各部门人员统计，各文件列名略有差异但语义相同。

核心能力：
- 列名相似性自动对齐（编辑距离 < 阈值时视为同一列）
- 自动填充缺失列（NaN）
- 新增 source_file 列标识每行来源
- 第 1 个文件为主表，其余文件按列相似性对齐后纵向 concat
- 单文件时退化为普通 FileAdapter 行为
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Optional

import pandas as pd
from difflib import SequenceMatcher

from service.constants import CSV_ENCODINGS
from service.viz_data.adapters.base import AdapterError, VizDataAdapter
from service.viz_data.capabilities import AdapterCapabilities
from service.viz_data.schema import DataRef, RawDataBundle, TabularBlock, VizDataset
from service.viz_data.source_descriptor import SourceDescriptor
from service.viz_data.storage import new_dataset_dir, save_dataframe_to_parquet

if TYPE_CHECKING:
    from service.query_engine import QueryEngine


class MultiExcelAdapter(VizDataAdapter):
    """合并多个 Excel / CSV 文件为单个 VizDataset。

    Args:
        file_paths: Excel/CSV 文件路径列表
        similarity_threshold: 列名相似性阈值（0-1），低于此值视为不同列
        add_source_column: 是否增加 source_file 列标识每行来源
        dataset_name: 数据集名称（默认取第一个文件名）
    """

    def __init__(
        self,
        file_paths: list[str],
        similarity_threshold: float = 0.65,
        add_source_column: bool = True,
        dataset_name: Optional[str] = None,
    ):
        self.file_paths = list(file_paths or [])
        self.similarity_threshold = similarity_threshold
        self.add_source_column = add_source_column
        self.dataset_name = dataset_name or (
            Path(self.file_paths[0]).stem if self.file_paths else "multi_excel"
        )

        # 对齐结果缓存，供 normalize 使用
        self._column_mapping: Optional[dict[int, dict[str, str]]] = None
        self._standard_columns: Optional[list[str]] = None

    def source_kind(self) -> str:
        return "file"

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(needs_llm=False, supports_multi_query=True)

    def validate(self) -> None:
        if not self.file_paths:
            raise AdapterError("MultiExcelAdapter 需要至少一个文件")
        if len(self.file_paths) == 1:
            return  # 退化为单文件

        for p in self.file_paths:
            path = Path(p)
            if not path.exists():
                raise AdapterError(f"文件不存在: {p}")
            if path.suffix.lower() not in (".xlsx", ".xls", ".csv"):
                raise AdapterError(f"仅支持 .xlsx / .xls / .csv，不支持: {path.suffix}")

    async def fetch(self, engine: "QueryEngine | None") -> RawDataBundle:
        """Phase 1: 计算列相似性对齐 → 读所有文件 → concat → 落盘 parquet。"""
        dataset_dir = new_dataset_dir()

        # Step 1: 读所有文件的列名（只读表头，避免大文件 IO）
        file_columns: list[tuple[str, list[str]]] = []
        for path in self.file_paths:
            cols = list(self._peek_columns(path))
            file_columns.append((path, cols))

        # Step 2: 计算列名相似性，构建标准列名集合（以第一个文件为基准）
        if len(file_columns) <= 1:
            # 只有一个文件，不需要对齐
            self._standard_columns = file_columns[0][1]
            self._column_mapping = {0: {c: c for c in self._standard_columns}}
        else:
            self._build_column_mapping(file_columns)

        # Step 3: 按映射关系读所有文件并对齐列 → concat
        dfs = []
        for file_idx, (path, cols) in enumerate(file_columns):
            df = self._read_file_as_dataframe(path)
            mapping = self._column_mapping[file_idx] if self._column_mapping else {}

            # 重命名并补齐缺失列
            df = df.rename(columns=mapping)
            for std_col in self._standard_columns or []:
                if std_col not in df.columns:
                    df[std_col] = None

            # 丢弃不在标准列集中的列
            df = df[[c for c in self._standard_columns or [] if c in df.columns]]

            # 增加来源文件标识
            if self.add_source_column:
                df["source_file"] = Path(path).name

            dfs.append(df)

        merged_df = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()

        # 清理：所有列对象类型统一转字符串（空值保持 NaN）
        for col in merged_df.columns:
            if merged_df[col].dtype == object:
                try:
                    numeric = pd.to_numeric(merged_df[col], errors="coerce")
                    if numeric.notna().mean() >= 0.5:
                        merged_df[col] = numeric
                except Exception:
                    pass

        # Step 4: 落盘 parquet
        parquet_path = dataset_dir / "merged.parquet"
        save_dataframe_to_parquet(merged_df, parquet_path)

        return RawDataBundle(
            dataset_dir=str(dataset_dir),
            tabular_files=[{
                "path": str(parquet_path),
                "total_files": len(self.file_paths),
                "shape": [len(merged_df), len(merged_df.columns)],
                "columns": list(merged_df.columns),
                "column_mapping": self._column_mapping,
            }],
            meta={
                "source": "multi_excel",
                "files": self.file_paths,
                "similarity_threshold": self.similarity_threshold,
            },
        )

    def normalize(self, raw: RawDataBundle) -> VizDataset:
        """Phase 2: 从合并后的 parquet 构建 VizDataset。"""
        tabular_files = raw.tabular_files or []
        if not tabular_files:
            raise AdapterError("MultiExcelAdapter.normalize: 没有 tabular_files")

        parquet_path = tabular_files[0]["path"]
        df = pd.read_parquet(parquet_path)

        from service.viz_data.introspection.df_stats import dataframe_to_column_schemas

        columns = dataframe_to_column_schemas(df)
        preview_rows = [df.columns.tolist()] + df.head(10).fillna("").values.tolist()

        tabular = TabularBlock(
            columns=columns,
            row_count=len(df),
            preview_rows=preview_rows,
            data_ref=DataRef(
                kind="parquet",
                path=str(Path(parquet_path).resolve()),
                size_bytes=Path(parquet_path).stat().st_size,
            ),
        )

        return VizDataset(
            name=self.dataset_name,
            source_kind="file",
            tabular=tabular,
            descriptor=SourceDescriptor(
                kind="file",
                label=f"{self.dataset_name} ({len(self.file_paths)} 文件)",
                logical_id=f"multi_excel_{Path(self.file_paths[0]).stem}" if self.file_paths else "multi_excel",
                extra={
                    "total_files": len(self.file_paths),
                    "columns_matched": tabular_files[0].get("column_mapping"),
                },
            ),
        )

    # -------- 内部工具 --------

    def _build_column_mapping(self, file_columns: list[tuple[str, list[str]]]) -> None:
        """构建每个文件的列名 -> 标准列名的映射。

        以第一个文件的列名为基准集，后续每个文件计算与基准列的编辑距离。
        """
        base_path, base_cols = file_columns[0]
        standard = list(base_cols)  # 不修改原列表

        mapping: dict[int, dict[str, str]] = {}
        mapping[0] = {c: c for c in standard}  # 基准文件 1:1 映射

        for file_idx in range(1, len(file_columns)):
            _, file_cols = file_columns[file_idx]
            file_map = {}

            for col in file_cols:
                best_match = None
                best_score = -1.0
                for std_col in standard:
                    score = SequenceMatcher(None, col.lower(), std_col.lower()).ratio()
                    if score > best_score:
                        best_score = score
                        best_match = std_col
                if best_score >= self.similarity_threshold:
                    file_map[col] = best_match
                else:
                    # 相似性不足，作为新列加入标准集
                    standard.append(col)
                    file_map[col] = col

            mapping[file_idx] = file_map

        self._standard_columns = standard
        self._column_mapping = mapping

    @staticmethod
    def _peek_columns(file_path: str) -> list[str]:
        """只读取文件列名，避免大文件全量 IO。"""
        path = Path(file_path)
        suffix = path.suffix.lower()

        if suffix in (".xlsx", ".xls"):
            df = pd.read_excel(path, nrows=0)
            return list(df.columns)
        elif suffix == ".csv":
            for enc in CSV_ENCODINGS:
                try:
                    df = pd.read_csv(path, nrows=0, encoding=enc)
                    return list(df.columns)
                except UnicodeDecodeError:
                    continue
            # fallback：latin1 兜底
            df = pd.read_csv(path, nrows=0, encoding="latin1")
            return list(df.columns)
        else:
            return []

    @staticmethod
    def _read_file_as_dataframe(file_path: str) -> pd.DataFrame:
        """读整个文件（与 FileAdapter 读取逻辑保持一致）。"""
        path = Path(file_path)
        suffix = path.suffix.lower()

        if suffix in (".xlsx", ".xls"):
            return pd.read_excel(str(path))
        elif suffix == ".csv":
            for enc in CSV_ENCODINGS:
                try:
                    return pd.read_csv(str(path), encoding=enc)
                except UnicodeDecodeError:
                    continue
            return pd.read_csv(str(path), encoding="latin1")
        else:
            raise AdapterError(f"不支持的文件类型: {suffix}")

    def _sync_fetch(self) -> RawDataBundle:
        """同步版本 fetch（供 FolderAdapter 调用）。"""
        import asyncio

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.fetch(None))
        finally:
            loop.close()
