"""CSV/JSON/Parquet 文件 Reader。

DuckDB 原生支持这些格式，直接用 SQL 读取并注册为表。
无需 pandas 预处理，DuckDB 自动推断类型。
"""

from __future__ import annotations

from pathlib import Path

from service.data_ingestion.duckdb_manager import DuckDBManager
from service.data_ingestion.models import DataProfile
from service.data_ingestion.profiler import build_profile


# 文件扩展名 -> DuckDB 注册方法
_EXT_MAP = {
    ".csv": "register_csv",
    ".tsv": "register_csv",
    ".json": "register_json",
    ".jsonl": "register_json",
    ".ndjson": "register_json",
    ".parquet": "register_parquet",
}


class FileReader:
    """读取 CSV/TSV/JSON/Parquet 文件，注册为 DuckDB 表。"""

    @staticmethod
    def can_handle(path: str) -> bool:
        ext = Path(path).suffix.lower()
        return ext in _EXT_MAP

    @staticmethod
    def read(
        db: DuckDBManager,
        path: str,
        table_name: str | None = None,
    ) -> DataProfile:
        """读取文件并注册为 DuckDB 表，返回 DataProfile。"""
        ext = Path(path).suffix.lower()
        if ext not in _EXT_MAP:
            raise ValueError(f"FileReader 不支持 {ext} 格式")

        name = table_name or DuckDBManager.safe_table_name(Path(path).name)
        method = getattr(db, _EXT_MAP[ext])
        method(name, path)

        return build_profile(db, name, source_kind="file", source_path=path)
