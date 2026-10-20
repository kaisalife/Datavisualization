"""Excel 合并表头 / 标题行解析回归。"""
from pathlib import Path

import pandas as pd
import pytest
from openpyxl import Workbook

from service.data_ingestion.readers.excel_reader import ExcelReader


def _new(path: Path):
    wb = Workbook()
    return wb, wb.active


def _two_level_header(ws, start_row: int = 1):
    """写一个两行合并表头（A 列纵向合并 + 年度横向合并）。"""
    r = start_row
    ws.cell(r, 1, "城市")
    ws.merge_cells(start_row=r, start_column=1, end_row=r + 1, end_column=1)
    ws.cell(r, 2, "2023 年")
    ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=3)
    ws.cell(r, 4, "2024 年")
    ws.merge_cells(start_row=r, start_column=4, end_row=r, end_column=5)
    for col, (year, metric) in enumerate(
        [(None, None), ("2023", "销售额"), ("2023", "利润"), ("2024", "销售额"), ("2024", "利润")],
        start=1,
    ):
        if metric:
            ws.cell(r + 1, col, metric)
    data = [
        ["北京", 1200, 300, 1500, 400],
        ["上海", 1100, 280, 1400, 360],
        ["广州", 900, 210, 1250, 300],
    ]
    for offset, row in enumerate(data, start=r + 2):
        for col, value in enumerate(row, start=1):
            ws.cell(offset, col, value)


def test_two_level_merged_header(tmp_path: Path):
    path = tmp_path / "sales.xlsx"
    wb, ws = _new(path)
    _two_level_header(ws)
    wb.save(path)

    table = ExcelReader.read(str(path))[0]

    assert list(table.df.columns) == [
        "城市",
        "2023 年_销售额",
        "2023 年_利润",
        "2024 年_销售额",
        "2024 年_利润",
    ]
    assert len(table.df) == 3
    assert table.df.iloc[0].tolist() == ["北京", 1200, 300, 1500, 400]
    assert table.df["2024 年_销售额"].tolist() == [1500, 1400, 1250]


def test_title_row_plus_merged_header(tmp_path: Path):
    path = tmp_path / "report.xlsx"
    wb, ws = _new(path)
    ws["A1"] = "2024 年各城市销售报表"
    ws.merge_cells("A1:E1")
    _two_level_header(ws, start_row=2)
    wb.save(path)

    df = ExcelReader.read(str(path))[0].df

    assert list(df.columns) == [
        "城市",
        "2023 年_销售额",
        "2023 年_利润",
        "2024 年_销售额",
        "2024 年_利润",
    ]
    assert df["城市"].tolist() == ["北京", "上海", "广州"]


def test_title_row_with_normal_header(tmp_path: Path):
    path = tmp_path / "title_only.xlsx"
    wb, ws = _new(path)
    ws["A1"] = "2024 年销售报表"
    ws.merge_cells("A1:C1")
    ws.append(["城市", "销售额", "利润"])
    ws.append(["北京", 1500, 400])
    ws.append(["上海", 1400, 360])
    wb.save(path)

    df = ExcelReader.read(str(path))[0].df

    assert list(df.columns) == ["城市", "销售额", "利润"]
    assert df["销售额"].tolist() == [1500, 1400]


def test_normal_sheet_keeps_pandas_behaviour(tmp_path: Path):
    path = tmp_path / "normal.xlsx"
    wb, ws = _new(path)
    ws.append(["城市", "销售额"])
    ws.append(["北京", 1500])
    ws.append(["上海", 1400])
    wb.save(path)

    reader_df = ExcelReader.read(str(path))[0].df
    pandas_df = pd.read_excel(path)

    pd.testing.assert_frame_equal(reader_df, pandas_df)


def test_merged_data_cells_do_not_move_header(tmp_path: Path):
    path = tmp_path / "data_merge.xlsx"
    wb, ws = _new(path)
    ws.append(["城市", "销售额"])
    ws["A2"] = "北京"
    ws.merge_cells("A2:A3")
    ws["B2"] = 1500
    ws["B3"] = 1600
    wb.save(path)

    df = ExcelReader.read(str(path))[0].df

    assert list(df.columns) == ["城市", "销售额"]
    assert len(df) == 2
    assert df["销售额"].tolist() == [1500, 1600]


def test_multiple_sheets_and_sheet_name(tmp_path: Path):
    path = tmp_path / "multi.xlsx"
    wb = Workbook()
    summary = wb.active
    summary.title = "汇总"
    _two_level_header(summary)
    detail = wb.create_sheet("明细")
    detail.append(["月份", "销量"])
    detail.append(["1 月", 10])
    detail.append(["2 月", 20])
    wb.save(path)

    tables = ExcelReader.read(str(path))

    assert [t.name for t in tables] == ["multi", "multi_sheet2"]
    assert "2023 年_销售额" in tables[0].df.columns
    assert list(tables[1].df.columns) == ["月份", "销量"]

    by_name = ExcelReader.read(str(path), sheet_name="汇总")[0]
    assert "2024 年_利润" in by_name.df.columns

    by_index = ExcelReader.read(str(path), sheet_name=1)[0]
    assert list(by_index.df.columns) == ["月份", "销量"]


def test_duplicate_leaf_names_get_unique_suffix(tmp_path: Path):
    path = tmp_path / "dup.xlsx"
    wb, ws = _new(path)
    ws["A1"] = "城市"
    ws["B1"] = "销售额"
    ws["C1"] = "销售额"
    ws.merge_cells("A1:A2")
    ws.merge_cells("B1:C1")
    ws["B2"] = "2023"
    ws["C2"] = "2024"
    ws.append(["北京", 100, 200])
    wb.save(path)

    df = ExcelReader.read(str(path))[0].df

    # 纵向合并的 A 列只有一个名字；横向合并的子列名不同
    assert list(df.columns) == ["城市", "销售额_2023", "销售额_2024"]


@pytest.mark.parametrize("name", ["books.xlsx", "books.xlsm"])
def test_xlsm_and_xlsx_are_supported(tmp_path: Path, name: str):
    path = tmp_path / name
    wb, ws = _new(path)
    _two_level_header(ws)
    wb.save(path)

    df = ExcelReader.read(str(path))[0].df
    assert "2023 年_销售额" in df.columns


def test_blank_cell_two_row_header(tmp_path: Path):
    """没有合并且靠空白格表达的两行表头也要能拼列名。"""
    path = tmp_path / "unmerged.xlsx"
    wb, ws = _new(path)
    ws.append(["城市", "2023 年", None, "2024 年", None])
    ws.append([None, "销售额", "利润", "销售额", "利润"])
    ws.append(["北京", 1200, 300, 1500, 400])
    ws.append(["上海", 1100, 280, 1400, 360])
    wb.save(path)

    df = ExcelReader.read(str(path))[0].df

    assert list(df.columns) == [
        "城市",
        "2023 年_销售额",
        "2023 年_利润",
        "2024 年_销售额",
        "2024 年_利润",
    ]
    assert len(df) == 2
    assert df["2024 年_销售额"].tolist() == [1500, 1400]


def test_blank_cell_but_data_row_not_treated_as_header(tmp_path: Path):
    """第二行首列有值 + 含数字，是数据行，不能当表头吃掉。"""
    path = tmp_path / "not_header.xlsx"
    wb, ws = _new(path)
    ws.append(["城市", None, "地区"])
    ws.append(["北京", "华北", "北方"])
    ws.append(["上海", 1200, "南方"])
    wb.save(path)

    df = ExcelReader.read(str(path))[0].df

    assert list(df.columns) == ["城市", "Unnamed: 1", "地区"]
    assert df.iloc[0].tolist() == ["北京", "华北", "北方"]
    assert len(df) == 2


def test_blank_cell_with_numeric_second_row_is_data(tmp_path: Path):
    path = tmp_path / "numeric_row.xlsx"
    wb, ws = _new(path)
    ws.append(["城市", "销售额"])
    ws.append([None, 1200])
    ws.append(["上海", 1400])
    wb.save(path)

    df = ExcelReader.read(str(path))[0].df

    assert list(df.columns) == ["城市", "销售额"]
    assert len(df) == 2


async def test_merged_header_reaches_data_profile(tmp_path: Path):
    """走完整 ingest：合并表头列名要进入 schema 和 series，而不是 Unnamed。"""
    from service.data_ingestion import DataSource, ingest

    path = tmp_path / "merged_profile.xlsx"
    wb, ws = _new(path)
    _two_level_header(ws)
    wb.save(path)

    profile = await ingest(DataSource(kind="file", path=str(path), name="merged"))

    assert [c["name"] for c in profile.schema] == [
        "城市",
        "2023 年_销售额",
        "2023 年_利润",
        "2024 年_销售额",
        "2024 年_利润",
    ]
    assert profile.row_count == 3
    assert len(profile.series_catalog.series) == 3
