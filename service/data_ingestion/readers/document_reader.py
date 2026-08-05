"""PDF/DOCX/图片 文档 Reader。

使用 Unstructured.io 解析非结构化文档，提取表格和文本，
转为 DataFrame 后注册到 DuckDB。

支持格式: PDF, DOCX, DOC, PPTX, HTML, 图片 (PNG/JPG/TIFF)
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from service.data_ingestion.duckdb_manager import DuckDBManager
from service.data_ingestion.models import DataProfile
from service.data_ingestion.profiler import build_profile, build_profiles_for_multiple_tables


# 支持的文档格式
_DOC_EXTS = {".pdf", ".docx", ".doc", ".pptx", ".ppt", ".html", ".htm", ".txt", ".md"}
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tiff", ".bmp"}


class DocumentReader:
    """使用 Unstructured.io 解析文档，提取表格注册为 DuckDB 表。"""

    @staticmethod
    def can_handle(path: str) -> bool:
        ext = Path(path).suffix.lower()
        return ext in _DOC_EXTS or ext in _IMAGE_EXTS

    @staticmethod
    def read(
        db: DuckDBManager,
        path: str,
        table_name: str | None = None,
        strategy: str = "auto",
    ) -> DataProfile:
        """解析文档并注册为 DuckDB 表。

        Args:
            db: DuckDBManager 实例
            path: 文档文件路径
            table_name: 目标表名
            strategy: Unstructured 解析策略 ("auto" / "hi_res" / "ocr_only" / "fast")

        Returns:
            DataProfile (多表格时 related_tables 包含其余表)
        """
        try:
            from unstructured.partition.auto import partition
        except ImportError:
            raise ImportError(
                "unstructured 未安装。请运行: pip install 'unstructured[all-docs]'"
            )

        # 解析文档
        kwargs = {"filename": path}
        ext = Path(path).suffix.lower()

        if ext == ".pdf":
            kwargs["strategy"] = strategy
        elif ext in _IMAGE_EXTS:
            kwargs["strategy"] = strategy

        elements = partition(**kwargs)

        # 提取表格元素
        tables = [el for el in elements if el.category == "Table"]

        base_name = table_name or DuckDBManager.safe_table_name(Path(path).name)

        if not tables:
            # 没有表格，提取文本作为单列表
            texts = [
                el.text.strip()
                for el in elements
                if el.text and el.text.strip()
            ]
            if not texts:
                raise ValueError(f"文档中未提取到任何内容: {path}")
            df = pd.DataFrame({"content": texts})
            db.register_dataframe(base_name, df)
            return build_profile(db, base_name, source_kind="document", source_path=path)

        # 将表格元素转为 DataFrame
        dataframes = []
        for i, table_el in enumerate(tables):
            try:
                # Unstructured Table 元素有 to_dataframe() 方法
                if hasattr(table_el, "to_dataframe"):
                    df = table_el.to_dataframe()
                else:
                    # fallback: 从 HTML 解析
                    import io
                    html_content = str(table_el)
                    dfs = pd.read_html(io.StringIO(html_content))
                    df = dfs[0] if dfs else pd.DataFrame({"content": [table_el.text]})

                # 清理列名
                df.columns = [str(c).strip() if str(c).strip() else f"col_{j}" for j, c in enumerate(df.columns)]
                dataframes.append(df)
            except Exception as e:
                # 单个表格解析失败不影响其他表格
                print(f"[DocumentReader] 表格 {i} 解析失败: {e}")
                continue

        if not dataframes:
            raise ValueError(f"文档中的表格均解析失败: {path}")

        if len(dataframes) == 1:
            db.register_dataframe(base_name, dataframes[0])
            return build_profile(db, base_name, source_kind="document", source_path=path)

        # 多表格: 每个注册为单独的表
        table_specs = []
        for i, df in enumerate(dataframes):
            name = base_name if i == 0 else f"{base_name}_table{i + 1}"
            db.register_dataframe(name, df)
            table_specs.append((name, "document", f"{path}#table{i + 1}"))

        profiles = build_profiles_for_multiple_tables(db, table_specs)
        return profiles[0]
