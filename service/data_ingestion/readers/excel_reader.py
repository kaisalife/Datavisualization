"""Excel 文件 Reader（v4）。

用 pandas 读取 Excel 为 DataFrame，返回 list[RawTable]。
多 sheet 场景: 每个 sheet 一个 RawTable。

中文报表常见两类表头问题，这里在 pandas 之前先处理：
1. 表格上方有一行合并的大标题（如 A1:E1「2024 年销售报表」）；
2. 两行合并表头（如 B1:C1「2023 年」+ B2「销售额」/ C2「利润」）。

合并区域直接从 xlsx/xlsm 的 XML 里读（zip + workbook rels），不加载整个
openpyxl 工作簿；没有表头问题时完全走原来的 pandas 路径，不改变既有行为。
三行以上表头只取前三行。
"""

from __future__ import annotations

import math
import re
import zipfile
from numbers import Number
from pathlib import Path
from xml.etree import ElementTree as ET

import pandas as pd
from openpyxl.utils import range_boundaries

from service.data_ingestion.models import RawTable, safe_table_name

# 多级表头最多支持 3 行；再高基本是排版产物
_MAX_HEADER_ROWS = 3
# 标题行的合并宽度阈值：至少占表格宽度的一半
_TITLE_SPAN_RATIO = 0.5
# 只看前 30 行就能判断表头（标题最多 2 行 + 表头 3 行）
_PEEK_ROWS = 30

_MAIN_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
_MERGE_CELL_RE = re.compile(rb'<(?:[A-Za-z0-9]+:)?mergeCell\b[^>]*\bref="([^"]+)"')


def _is_blank(value) -> bool:
    """空单元格 / 空白字符串 / NaN 都算空。"""
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return isinstance(value, str) and not value.strip()


def _is_number(value) -> bool:
    return isinstance(value, Number) and not isinstance(value, bool)


def _header_text(value) -> str:
    """表头文本：整数型浮点（pandas 为对齐 NaN 转的 float）去掉 .0。"""
    if _is_number(value):
        number = float(value)
        if number.is_integer():
            return str(int(number))
    return str(value).strip()


def _sheet_names(path: str) -> list[str] | None:
    """直接从 workbook.xml 读 sheet 名，避免为拿名字再加载一次工作簿。"""
    if Path(path).suffix.lower() not in {".xlsx", ".xlsm"}:
        return None
    try:
        with zipfile.ZipFile(path) as zf:
            workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    except (KeyError, OSError, zipfile.BadZipFile, ET.ParseError):
        return None
    names = [sheet.get("name") for sheet in workbook.iter(f"{_MAIN_NS}sheet")]
    return [name for name in names if name]


def _sheet_xml_path(zf: zipfile.ZipFile, sheet_name: str) -> str | None:
    """根据 sheet 名找到对应的 worksheet XML 路径。"""
    try:
        workbook = ET.fromstring(zf.read("xl/workbook.xml"))
        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    except (KeyError, ET.ParseError):
        return None
    rel_map = {rel.get("Id"): rel.get("Target") for rel in rels}
    for sheet in workbook.iter(f"{_MAIN_NS}sheet"):
        if sheet.get("name") != sheet_name:
            continue
        target = rel_map.get(sheet.get(_REL_ID))
        if not target:
            return None
        target = target.replace("\\", "/")
        if target.startswith("/"):
            return target.lstrip("/")
        return target if target.startswith("xl/") else f"xl/{target}"
    return None


def _merged_ranges(path: str, sheet_name: str) -> list[tuple[int, int, int, int]] | None:
    """读取 sheet 的合并区域，返回 [(min_row, min_col, max_row, max_col)]。

    返回 None 表示无法解析（例如老 .xls），调用方直接走 pandas。
    """
    if Path(path).suffix.lower() not in {".xlsx", ".xlsm"}:
        return None
    try:
        with zipfile.ZipFile(path) as zf:
            xml_path = _sheet_xml_path(zf, sheet_name)
            if not xml_path:
                return None
            data = zf.read(xml_path)
    except (KeyError, OSError, zipfile.BadZipFile):
        return None

    ranges: list[tuple[int, int, int, int]] = []
    for match in _MERGE_CELL_RE.finditer(data):
        try:
            min_col, min_row, max_col, max_row = range_boundaries(match.group(1).decode("ascii"))
        except Exception:
            continue
        ranges.append((min_row, min_col, max_row, max_col))
    return ranges


def _fill_merged_values(rows: list[list], ranges) -> list[list]:
    """把合并单元格左上角的值填满整个区域（只用于表头解析）。"""
    filled = [list(row) for row in rows]
    if not filled:
        return filled
    for min_row, min_col, max_row, max_col in ranges:
        if min_row > len(filled) or min_col > len(filled[0]):
            continue
        value = filled[min_row - 1][min_col - 1]
        for r in range(min_row - 1, min(max_row, len(filled))):
            for c in range(min_col - 1, min(max_col, len(filled[r]))):
                filled[r][c] = value
    return filled


def _fill_merged_data_cells(
    df: pd.DataFrame,
    ranges,
    data_start_row: int,
) -> pd.DataFrame:
    """把数据区「纵向合并」的文本值向下填满。

    中文报表常见 ``城市`` 在连续几行合并（北京 跨 1/2 月），pandas 只保留首行，
    其余行变 NaN，拆 series 时会丢类别。这里只处理：

    - 纵向合并（同一列，多行）；
    - 左上角是文本（数值合并多为合计/小计，向下填会重复计量）；
    - 区域完全落在数据行内（不碰表头）。

    Args:
        df: pandas 读出的数据（不含表头）
        ranges: [(min_row, min_col, max_row, max_col)]，1-based 闭区间
        data_start_row: df 第 0 行对应的工作表 0-based 行号
    """
    if df.empty or not ranges:
        return df
    filled = df.copy()
    n_rows, n_cols = filled.shape
    for min_row, min_col, max_row, max_col in ranges:
        if max_row <= min_row or max_col != min_col:
            continue  # 只处理纵向合并
        row_start = min_row - 1 - data_start_row
        row_end = max_row - 1 - data_start_row
        col = min_col - 1
        if row_start < 0 or row_end >= n_rows or col >= n_cols:
            continue
        value = filled.iat[row_start, col]
        if _is_blank(value) or _is_number(value):
            continue
        filled.iloc[row_start : row_end + 1, col] = value
    return filled


def _title_row_index(rows: list[list], ranges, width: int, row_offset: int = 0) -> int | None:
    """识别表格顶部「跨多列的单值合并行」，返回相对 ``rows`` 的 0-based 行号。

    Args:
        rows: 待检查的行（可以是整个 sheet 的切片）
        ranges: [(min_row, min_col, max_row, max_col)]，绝对行号
        width: 表格宽度
        row_offset: ``rows[0]`` 在 sheet 中的 0-based 行号，用于对齐合并区域

    只有下一行确实有多个单元格内容时才认定为标题，避免把单列表格误杀。
    """
    if not rows:
        return None
    min_span = max(2, int(width * _TITLE_SPAN_RATIO))
    for row_idx in range(min(2, len(rows))):
        row = rows[row_idx]
        nonempty = sum(1 for v in row if not _is_blank(v))
        if nonempty > 1:
            continue
        abs_row = row_offset + row_idx + 1
        has_wide_merge = any(
            min_row == abs_row and (max_col - min_col + 1) >= min_span
            for min_row, min_col, max_row, max_col in ranges
        )
        if not has_wide_merge:
            continue
        next_row = rows[row_idx + 1] if row_idx + 1 < len(rows) else []
        if sum(1 for v in next_row if not _is_blank(v)) >= 2:
            return row_idx
    return None


def _blank_header_layout(rows: list[list], width: int) -> tuple[list[str], int] | None:
    """识别「没有合并、靠空白格表达两级关系」的两行表头。

    典型形态（A 列纵向合并被拆开后会变成这样）::

        城市 | 2023 年 |        | 2024 年 |
             | 销售额  | 利润   | 销售额  | 利润

    仅在同时满足以下条件时接管，避免把数据行误判成表头：
    - 第一行有空白格且至少 2 个非空值；
    - 第二行首列为空（纵向合并拆开后留下的空位）、非空值比第一行多、且全是文字；
    - 第三行至少有一个数字（数据行）。

    Returns:
        (列名列表, 需要跳过的行数)；不适用时返回 None。
    """
    if len(rows) < 3 or width <= 0:
        return None
    rows = [list(row) + [None] * (width - len(row)) for row in rows[:3]]
    first, second, third = rows

    first_values = [v for v in first if not _is_blank(v)]
    second_values = [v for v in second if not _is_blank(v)]
    if len(first_values) < 2 or len(second_values) <= len(first_values):
        return None
    if not _is_blank(second[0]):
        return None
    if any(_is_number(v) for v in second_values):
        return None
    if not any(_is_number(v) for v in third):
        return None

    headers: list[str] = []
    seen: dict[str, int] = {}
    parent = None
    for col in range(width):
        if not _is_blank(first[col]):
            parent = _header_text(first[col])
        child = "" if _is_blank(second[col]) else _header_text(second[col])
        parts = [p for p in (parent, child) if p]
        if len(parts) == 2 and parts[0] == parts[1]:
            parts = parts[:1]
        name = "_".join(parts) if parts else f"Unnamed: {col}"
        if name in seen:
            seen[name] += 1
            name = f"{name}.{seen[name]}"
        else:
            seen[name] = 0
        headers.append(name)
    return headers, 2


def _merged_header_layout(
    rows: list[list], ranges, width: int
) -> tuple[list[str], int] | None:
    """把多行合并表头压成单行。

    Returns:
        (列名列表, 需要跳过的行数)；不适用（表头无合并）时返回 None。
    """
    if not ranges or not rows or width <= 0:
        return None
    rows = [list(row) + [None] * (width - len(row)) for row in rows]

    # 1) 跳过顶部空行
    start = 0
    while start < len(rows) and all(_is_blank(v) for v in rows[start]):
        start += 1
    if start >= len(rows):
        return None

    # 2) 跳过合并大标题（可能不止一行）
    while True:
        title_idx = _title_row_index(rows[start:], ranges, width, row_offset=start)
        if title_idx is None:
            break
        start += title_idx + 1

    filled = _fill_merged_values(rows, ranges)

    # 3) 表头行数：取「与首行表头相交的合并区域」的最大纵向跨度
    first_header_row = start + 1  # openpyxl 行号从 1 开始
    header_ranges = [
        (min_row, min_col, max_row, max_col)
        for min_row, min_col, max_row, max_col in ranges
        if min_row <= first_header_row <= max_row
    ]
    if not header_ranges:
        return None

    header_rows = 1
    for min_row, _min_col, max_row, _max_col in header_ranges:
        header_rows = max(header_rows, min(max_row - first_header_row + 1, _MAX_HEADER_ROWS))

    # 4) 横向合并 + 第二行是纯文字子表头 -> 两行表头（A 列未必有纵向合并）
    if header_rows == 1 and first_header_row < len(rows):
        second = rows[first_header_row]  # 0-based 的第二行
        second_nonempty = [v for v in second if not _is_blank(v)]
        has_horizontal = any(
            min_row == first_header_row
            and max_row == first_header_row
            and max_col > min_col
            for min_row, min_col, max_row, max_col in ranges
        )
        next_row = rows[first_header_row + 1] if first_header_row + 1 < len(rows) else []
        if (
            has_horizontal
            and second_nonempty
            and not any(_is_number(v) for v in second_nonempty)
            and any(_is_number(v) for v in next_row)
        ):
            header_rows = 2

    last_header_row = first_header_row + header_rows - 1

    # 5) 拼列名：纵向合并会产生重复值，连续重复只保留一个
    headers: list[str] = []
    seen: dict[str, int] = {}
    for col in range(width):
        parts: list[str] = []
        for r in range(first_header_row - 1, min(last_header_row, len(rows))):
            value = filled[r][col]
            if _is_blank(value):
                continue
            text = _header_text(value)
            if not parts or parts[-1] != text:
                parts.append(text)
        name = "_".join(parts) if parts else f"Unnamed: {col}"
        if name in seen:
            seen[name] += 1
            name = f"{name}.{seen[name]}"
        else:
            seen[name] = 0
        headers.append(name)

    return headers, last_header_row


def _fit_headers(headers: list[str], width: int) -> list[str]:
    """让列名数量与 DataFrame 实际列数一致。"""
    if len(headers) < width:
        headers = headers + [f"Unnamed: {i}" for i in range(len(headers), width)]
    return headers[:width]


def _read_with_headers(
    path: str,
    sheet: str | int,
    headers: list[str],
    skip: int,
    ranges=None,
) -> pd.DataFrame:
    """按表头解析结果读取数据行（跳过标题/表头，列名用合并后的名字）。"""
    df = pd.read_excel(path, sheet_name=sheet, header=None, skiprows=skip)
    if ranges:
        # 必须在 dropna/reset_index 之前按绝对行号填充
        df = _fill_merged_data_cells(df, ranges, skip)
    df.columns = _fit_headers(headers, df.shape[1])
    df = df.dropna(how="all").reset_index(drop=True)
    # 合并表头文件常在右侧留格式空列，整列为空的 Unnamed 列直接去掉
    empty_unnamed = [
        col for col in df.columns
        if str(col).startswith("Unnamed: ") and df[col].isna().all()
    ]
    if empty_unnamed:
        df = df.drop(columns=empty_unnamed)
    return df


def _title_skip_rows(rows: list[list], ranges, width: int) -> int:
    """没有合并表头、但顶部有合并大标题时，返回需要跳过的行数。"""
    idx = _title_row_index(rows, ranges, width)
    return idx + 1 if idx is not None else 0


class ExcelReader:
    """读取 Excel 文件，返回 list[RawTable]。"""

    @staticmethod
    def can_handle(path: str) -> bool:
        ext = Path(path).suffix.lower()
        return ext in {".xlsx", ".xls", ".xlsm"}

    @staticmethod
    def _read_sheet(path: str, sheet: str) -> pd.DataFrame:
        """优先处理合并表头/标题行，否则保持 pandas 原行为。"""
        ranges = _merged_ranges(path, sheet)
        if ranges is None:
            return pd.read_excel(path, sheet_name=sheet)
        if ranges:
            try:
                peek = pd.read_excel(path, sheet_name=sheet, header=None, nrows=_PEEK_ROWS)
                rows = peek.values.tolist()
                layout = _merged_header_layout(rows, ranges, peek.shape[1])
                if layout is not None:
                    headers, skip = layout
                    return _read_with_headers(path, sheet, headers, skip, ranges)
                skip = _title_skip_rows(rows, ranges, peek.shape[1])
                if skip:
                    df = pd.read_excel(path, sheet_name=sheet, skiprows=skip)
                    return _fill_merged_data_cells(df, ranges, skip + 1)
            except Exception:
                # 表头解析失败不影响主流程，退回 pandas
                pass
        else:
            # 没有任何合并：看看是不是靠空白格表达的两行表头
            try:
                peek = pd.read_excel(path, sheet_name=sheet, header=None, nrows=4)
                layout = _blank_header_layout(peek.values.tolist(), peek.shape[1])
                if layout is not None:
                    headers, skip = layout
                    return _read_with_headers(path, sheet, headers, skip)
            except Exception:
                pass
        df = pd.read_excel(path, sheet_name=sheet)
        # 默认 header=0：df 第 0 行对应工作表第 1 行（0-based）
        return _fill_merged_data_cells(df, ranges, 1)

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
        sheets = _sheet_names(path)
        if sheets is None:
            with pd.ExcelFile(path) as workbook:
                sheets = list(workbook.sheet_names)

        if sheet_name is not None:
            sheet = sheets[sheet_name] if isinstance(sheet_name, int) else sheet_name
            df = ExcelReader._read_sheet(path, sheet)
            return [RawTable(name=base_name, df=df, source_kind="file", source_path=path)]

        raw_tables = []
        for i, sheet in enumerate(sheets):
            name = base_name if i == 0 else f"{base_name}_sheet{i + 1}"
            df = ExcelReader._read_sheet(path, sheet)
            raw_tables.append(
                RawTable(name=name, df=df, source_kind="file", source_path=f"{path}#{sheet}")
            )
        return raw_tables
