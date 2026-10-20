"""表头清洗回归：首尾空白、制表符、重复列名。"""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from service.data_ingestion import DataSource, ingest


async def test_csv_header_whitespace_is_cleaned(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TEMP_DATASETS_DIR", str(tmp_path / "datasets"))
    path = tmp_path / "sales.csv"
    path.write_text(" 城市 \t, 销售  额 \n北京,1200\n上海,1300\n", encoding="utf-8")

    profile = await ingest(DataSource(kind="file", path=str(path), name="sales"))

    assert [col["name"] for col in profile.schema] == ["城市", "销售 额"]
    assert profile.preview[0]["城市"] == "北京"
    # 列名干净后，语义识别才能正常工作
    assert profile.column_semantics["销售 额"] == "measure"


async def test_duplicate_headers_get_suffixes(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TEMP_DATASETS_DIR", str(tmp_path / "datasets"))
    path = tmp_path / "dup.csv"
    path.write_text("城市, 城市 ,城市.1\n北京,上海,广州\n", encoding="utf-8")

    profile = await ingest(DataSource(kind="file", path=str(path), name="dup"))

    assert [col["name"] for col in profile.schema] == ["城市", "城市.1", "城市.1.1"]


async def test_excel_default_header_whitespace_is_cleaned(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TEMP_DATASETS_DIR", str(tmp_path / "datasets"))
    path = tmp_path / "sales.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append([" 城市 ", " 销售额 "])
    sheet.append(["北京", 1200])
    sheet.append(["上海", 1300])
    workbook.save(path)

    profile = await ingest(DataSource(kind="file", path=str(path), name="sales"))

    assert [col["name"] for col in profile.schema] == ["城市", "销售额"]
    assert profile.preview[0]["城市"] == "北京"
