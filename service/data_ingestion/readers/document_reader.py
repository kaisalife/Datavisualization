"""PDF/DOCX/图片 文档 Reader（v4）。

使用 Unstructured.io 解析非结构化文档，提取表格和文本至 DataFrame，
返回 list[RawTable]（不再注册到 DuckDB）。

支持格式: PDF, DOCX, DOC, PPTX, HTML, 图片 (PNG/JPG/TIFF)
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from service.data_ingestion.models import RawTable, safe_table_name
from service.observability import get_logger

logger = get_logger(__name__)


# 支持的文档格式
_DOC_EXTS = {".pdf", ".docx", ".doc", ".pptx", ".ppt", ".html", ".htm", ".txt", ".md"}
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tiff", ".bmp"}


class DocumentReader:
    """使用 Unstructured.io 解析文档，提取表格为 DataFrame。"""

    @staticmethod
    def can_handle(path: str) -> bool:
        ext = Path(path).suffix.lower()
        return ext in _DOC_EXTS or ext in _IMAGE_EXTS

    @staticmethod
    def read(
        path: str,
        table_name: str | None = None,
        strategy: str = "auto",
    ) -> list[RawTable]:
        """解析文档为 DataFrame 列表。

        Args:
            path: 文档文件路径
            table_name: 目标表名
            strategy: Unstructured 解析策略 ("auto" / "hi_res" / "ocr_only" / "fast")

        Returns:
            list[RawTable]（多表格时每个一条）
        """
        try:
            from unstructured.partition.auto import partition
        except ImportError:
            raise ImportError(
                "unstructured 未安装。请运行: pip install 'unstructured[all-docs]'"
            )

        kwargs = {"filename": path}
        ext = Path(path).suffix.lower()
        if ext == ".pdf" or ext in _IMAGE_EXTS:
            kwargs["strategy"] = strategy

        elements = partition(**kwargs)
        tables = [el for el in elements if el.category == "Table"]

        base_name = safe_table_name(table_name or Path(path).name)

        if not tables:
            texts = [el.text.strip() for el in elements if el.text and el.text.strip()]
            if not texts:
                raise ValueError(f"文档中未提取到任何内容: {path}")
            df = pd.DataFrame({"content": texts})
            return [RawTable(name=base_name, df=df, source_kind="document", source_path=path)]

        dataframes = []
        for i, table_el in enumerate(tables):
            try:
                if hasattr(table_el, "to_dataframe"):
                    df = table_el.to_dataframe()
                else:
                    import io
                    html_content = str(table_el)
                    dfs = pd.read_html(io.StringIO(html_content))
                    df = dfs[0] if dfs else pd.DataFrame({"content": [table_el.text]})
                df.columns = [
                    str(c).strip() if str(c).strip() else f"col_{j}"
                    for j, c in enumerate(df.columns)
                ]
                dataframes.append(df)
            except Exception as e:
                logger.warning("文档表格解析失败", table_index=i, error=str(e))
                continue

        if not dataframes:
            raise ValueError(f"文档中的表格均解析失败: {path}")

        return [
            RawTable(
                name=base_name if i == 0 else f"{base_name}_table{i + 1}",
                df=df,
                source_kind="document",
                source_path=f"{path}#table{i + 1}",
            )
            for i, df in enumerate(dataframes)
        ]