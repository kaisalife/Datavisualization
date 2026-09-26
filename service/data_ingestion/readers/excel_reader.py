"""Excel 文件 Reader（v4）。

用 pandas 读取 Excel 为 DataFrame，返回 list[RawTable]。
多 sheet 场景: 每个 sheet 一个 RawTable。
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from service.data_ingestion.models import RawTable, safe_table_name


class ExcelReader:
    """读取 Excel 文件，返回 list[RawTable]。"""

    @staticmethod
    def can_handle(path: str) -> bool:
        ext = Path(path).suffix.lower()
        return ext in {".xlsx", ".xls", ".xlsm"}

    @staticmethod
    def read(
        path: str,
        table_name: str | None = None,
        sheet_name: str | int | None = None,
    ) -> list[RawTable]:
        """读取 Excel 为 DataFrame 列表。

        Args:
            path: Excel 文件路径
            table_name: 逻辑表名 (可选，默认取文件名)
            sheet_name: 指定 sheet (None=全部)

        Returns:
            list[RawTable]（多 sheet 时每个一条）
        """
        base_name = safe_table_name(table_name or Path(path).name)

        if sheet_name is not None:
            df = pd.read_excel(path, sheet_name=sheet_name)
            if isinstance(df, dict):
                df = list(df.values())[0]
            return [RawTable(name=base_name, df=df, source_kind="file", source_path=path)]

        all_sheets = pd.read_excel(path, sheet_name=None)
        if not all_sheets:
            raise ValueError(f"Excel 文件无 sheet: {path}")

        raw_tables = []
        for i, (sheet, df) in enumerate(all_sheets.items()):
            name = base_name if i == 0 else f"{base_name}_sheet{i + 1}"
            raw_tables.append(RawTable(name=name, df=df, source_kind="file", source_path=f"{path}#{sheet}"))
        return raw_tables