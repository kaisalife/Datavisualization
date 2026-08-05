"""Excel 文件 Reader。

DuckDB 对 Excel 支持不完善，用 pandas 预处理：
- .xlsx / .xls -> pd.read_excel() -> DuckDB register_dataframe()
- 多 sheet 场景: 每个 sheet 注册为单独的表，第一个表为 primary
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from service.data_ingestion.duckdb_manager import DuckDBManager
from service.data_ingestion.models import DataProfile
from service.data_ingestion.profiler import build_profile, build_profiles_for_multiple_tables


class ExcelReader:
    """读取 Excel 文件，注册为 DuckDB 表。"""

    @staticmethod
    def can_handle(path: str) -> bool:
        ext = Path(path).suffix.lower()
        return ext in {".xlsx", ".xls", ".xlsm"}

    @staticmethod
    def read(
        db: DuckDBManager,
        path: str,
        table_name: str | None = None,
        sheet_name: str | int | None = None,
    ) -> DataProfile:
        """读取 Excel 并注册为 DuckDB 表。

        Args:
            db: DuckDBManager 实例
            path: Excel 文件路径
            table_name: 目标表名 (可选)
            sheet_name: 指定 sheet (None=自动检测全部, 默认取第一个)

        Returns:
            DataProfile (多 sheet 时 related_tables 包含其余表)
        """
        base_name = table_name or DuckDBManager.safe_table_name(Path(path).name)

        if sheet_name is not None:
            # 指定单个 sheet
            df = pd.read_excel(path, sheet_name=sheet_name)
            if isinstance(df, dict):
                # sheet_name=None 时返回 dict, 但这里指定了具体 sheet
                df = list(df.values())[0]
            db.register_dataframe(base_name, df)
            return build_profile(db, base_name, source_kind="file", source_path=path)

        # 自动检测所有 sheet
        all_sheets = pd.read_excel(path, sheet_name=None)
        if not all_sheets:
            raise ValueError(f"Excel 文件无 sheet: {path}")

        if len(all_sheets) == 1:
            # 单 sheet
            df = list(all_sheets.values())[0]
            db.register_dataframe(base_name, df)
            return build_profile(db, base_name, source_kind="file", source_path=path)

        # 多 sheet: 每个注册为单独的表
        table_specs = []
        for i, (sheet, df) in enumerate(all_sheets.items()):
            name = base_name if i == 0 else f"{base_name}_sheet{i + 1}"
            db.register_dataframe(name, df)
            # 清理 sheet 名作为后缀
            safe_sheet = "".join(c if c.isalnum() or c == "_" else "_" for c in sheet)
            table_specs.append((name, "file", f"{path}#{sheet}"))

        profiles = build_profiles_for_multiple_tables(db, table_specs)
        return profiles[0]
