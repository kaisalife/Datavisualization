"""PDF 表格提取 Adapter。

支持上传 PDF 文件，自动识别其中所有表格，转成 VizDataset：
- 单表格 PDF：表格直接作为 dataset.tabular
- 多表格 PDF：第 1 张表为 dataset.tabular，其余表进 dataset.related_datasets
- 可选页码范围（如 "1,3,5-10"），默认全部页

适用场景：财务报表 PDF、行业研报、工资条 PDF、供应链账单 PDF。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import pandas as pd
import pdfplumber

from service.viz_data.adapters.base import AdapterError, VizDataAdapter
from service.viz_data.capabilities import AdapterCapabilities
from service.viz_data.schema import DataRef, RawDataBundle, TabularBlock, VizDataset
from service.viz_data.source_descriptor import SourceDescriptor
from service.viz_data.storage import new_dataset_dir, save_dataframe_to_parquet

if TYPE_CHECKING:
    from service.query_engine import QueryEngine


_PAGE_RANGE_PAT = re.compile(r"(\d+)(?:-(\d+))?")


class PdfAdapter(VizDataAdapter):
    """把 PDF 中的表格转成 VizDataset。

    Args:
        pdf_path: PDF 文件路径
        page_range: 页码范围字符串，如 "all" 或 "1,3,5-10"（1-based）
        table_settings: pdfplumber table 识别配置（dict，可选）
        dataset_name: 数据集名称（默认取文件名）
    """

    # PDF 提取的数据总是需要清洗（表格识别可能有噪声）
    auto_skip_if_clean = False

    def __init__(
        self,
        pdf_path: str | Path,
        page_range: str = "all",
        table_settings: Optional[dict] = None,
        dataset_name: Optional[str] = None,
    ):
        self.pdf_path = Path(pdf_path)
        self.page_range = page_range.strip().lower()
        self.table_settings = table_settings or {}
        self.dataset_name = dataset_name or self.pdf_path.stem

    def source_kind(self) -> str:
        return "file"

    def capabilities(self) -> AdapterCapabilities:
        # 纯规则提取，不需要 LLM
        return AdapterCapabilities(needs_llm=False, supports_multi_query=True)

    def validate(self) -> None:
        if not self.pdf_path.exists():
            raise AdapterError(f"PDF 文件不存在: {self.pdf_path}")
        if self.pdf_path.suffix.lower() != ".pdf":
            raise AdapterError(f"文件不是 PDF: {self.pdf_path.suffix}")

    async def fetch(self, engine: "QueryEngine | None") -> RawDataBundle:
        """Phase 1: 用 pdfplumber 提取所有表格，落盘成 parquet。

        每个表格生成一个单独的 parquet 文件（table_0.parquet, table_1.parquet, ...）。
        """
        dataset_dir = new_dataset_dir()

        # 解析页码范围
        pages_to_parse = self._parse_page_range()

        # 提取表格
        tables = []
        with pdfplumber.open(str(self.pdf_path)) as pdf:
            total_pages = len(pdf.pages)
            if pages_to_parse is None:
                page_indices = range(total_pages)
            else:
                page_indices = [p - 1 for p in pages_to_parse if 1 <= p <= total_pages]

            for idx in page_indices:
                page = pdf.pages[idx]
                page_tables = page.extract_tables(self.table_settings)
                for raw_table in page_tables:
                    if not raw_table or len(raw_table) < 2:
                        continue
                    # 清理空行、全 None 行
                    clean_table = []
                    for row in raw_table:
                        if row is None:
                            continue
                        clean_row = [v.strip() if isinstance(v, str) else v for v in row]
                        if all(v is None or v == "" for v in clean_row):
                            continue
                        clean_table.append(clean_row)
                    if len(clean_table) < 2:
                        continue
                    tables.append((idx + 1, clean_table))  # (页码, 表格数据)

        if not tables:
            raise AdapterError("PDF 中未识别到有效表格（要求至少 2 行数据，第 1 行作为表头）")

        # 每个表格落盘成 parquet
        tabular_files = []
        for table_idx, (page_num, raw_table) in enumerate(tables):
            df = self._table_to_dataframe(raw_table)
            if df.empty or len(df.columns) == 0:
                continue

            parquet_path = dataset_dir / f"table_{table_idx}.parquet"
            save_dataframe_to_parquet(df, parquet_path)

            tabular_files.append({
                "path": str(parquet_path),
                "page_number": page_num,
                "table_index": table_idx,
                "shape": [len(df), len(df.columns)],
                "columns": list(df.columns),
            })

        return RawDataBundle(
            dataset_dir=str(dataset_dir),
            tabular_files=tabular_files,
            meta={
                "source": "pdf",
                "original_file": str(self.pdf_path),
                "total_tables": len(tabular_files),
                "page_range": self.page_range,
            },
        )

    def normalize(self, raw: RawDataBundle) -> VizDataset:
        """Phase 2: 把落盘的表格组装成 VizDataset。

        - 第 1 张表格作为 dataset.tabular（主表）
        - 其余表格进入 dataset.related_datasets（可被 Planner 选择作为第二数据源）
        """
        tabular_files = raw.tabular_files or []
        if not tabular_files:
            raise AdapterError("PDF 提取后没有可用表格数据")

        dataset_dir = Path(raw.dataset_dir)
        related = []

        # 从第 1 张表构建主表
        main_info = tabular_files[0]
        main_df = pd.read_parquet(dataset_dir / Path(main_info["path"]).name)
        main_tabular = self._df_to_tabular_block(main_df, Path(main_info["path"]))

        # 其余表作为 related_datasets
        for info in tabular_files[1:]:
            df = pd.read_parquet(dataset_dir / Path(info["path"]).name)
            tabular = self._df_to_tabular_block(df, Path(info["path"]))
            related.append(VizDataset(
                name=f"{self.dataset_name}_表{info['table_index'] + 1}",
                source_kind="file",
                tabular=tabular,
                descriptor=SourceDescriptor(
                    kind="file",
                    label=f"PDF 第 {info['page_number']} 页 表 {info['table_index'] + 1}",
                    logical_id=f"pdf_table_{info['table_index']}",
                ),
            ))

        return VizDataset(
            name=self.dataset_name,
            source_kind="file",
            tabular=main_tabular,
            related_datasets=related,
            descriptor=SourceDescriptor(
                kind="file",
                label=f"PDF: {self.dataset_name}",
                logical_id=f"pdf_{self.pdf_path.stem}",
                extra={"total_tables": len(tabular_files)},
            ),
        )

    def _sync_fetch(self) -> RawDataBundle:
        """同步版本 fetch（供 FolderAdapter 调用）。"""
        import asyncio

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.fetch(None))
        finally:
            loop.close()

    # -------- 内部工具 --------

    def _parse_page_range(self) -> Optional[list[int]]:
        """解析 page_range 字符串。返回 None 表示全部页，否则返回页码列表（1-based）。"""
        if self.page_range == "all":
            return None

        pages = set()
        for part in self.page_range.split(","):
            part = part.strip()
            m = _PAGE_RANGE_PAT.match(part)
            if not m:
                continue
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else start
            pages.update(range(start, end + 1))

        return sorted(pages) if pages else None

    @staticmethod
    def _table_to_dataframe(raw_table: list[list]) -> pd.DataFrame:
        """把 pdfplumber 提取的原始表格（二维数组）转成 DataFrame。"""
        if not raw_table:
            return pd.DataFrame()

        header = raw_table[0]
        data_rows = raw_table[1:]

        # 处理表头全 None 的情况（直接用 col_0, col_1, ...）
        if all(v is None or str(v).strip() == "" for v in header):
            header = [f"col_{i}" for i in range(len(header))]
        else:
            header = [str(v).strip() if v is not None else f"col_{i}" for i, v in enumerate(header)]

        # 补全行长度不一致（空值填充）
        max_len = len(header)
        for row in data_rows:
            max_len = max(max_len, len(row))

        def pad_row(r: list, length: int) -> list:
            if len(r) >= length:
                return r[:length]
            return r + [None] * (length - len(r))

        header = pad_row(header, max_len)
        data = [pad_row(row, max_len) for row in data_rows]

        df = pd.DataFrame(data, columns=header)

        # 类型推断
        for col in df.columns:
            # 先尝试去逗号后转数字（财务报表常见 1,234.56）
            try:
                if df[col].dtype == object:
                    numeric = df[col].astype(str).str.replace(",", "").str.strip()
                    numeric = pd.to_numeric(numeric, errors="coerce")
                    if numeric.notna().mean() >= 0.8:
                        df[col] = numeric
            except Exception:
                pass

        return df

    @staticmethod
    def _df_to_tabular_block(df: pd.DataFrame, parquet_path: Path) -> TabularBlock:
        """DataFrame 转 TabularBlock（复用 file_adapter 的标准转换）。"""
        from service.viz_data.introspection.df_stats import dataframe_to_column_schemas

        columns = dataframe_to_column_schemas(df)
        preview_rows = [df.columns.tolist()] + df.head(10).fillna("").values.tolist()

        return TabularBlock(
            columns=columns,
            row_count=len(df),
            preview_rows=preview_rows,
            data_ref=DataRef(
                kind="parquet",
                path=str(parquet_path.resolve()),
                size_bytes=parquet_path.stat().st_size,
            ),
        )
