"""CSV 编码探测回归：GBK / UTF-8 BOM / UTF-16 都能正常读中文。"""
from __future__ import annotations

from pathlib import Path

import pytest

from service.data_ingestion.readers.file_reader import (
    FileReader,
    _detect_delimiter,
    _detect_encoding,
)

_SAMPLE = "城市,销售额\n北京,1200\n上海,1300\n"


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "gb18030", "utf-16"])
def test_detect_encoding_roundtrip(tmp_path: Path, encoding: str):
    path = tmp_path / "sales.csv"
    path.write_bytes(_SAMPLE.encode(encoding))

    detected = _detect_encoding(str(path))
    text = path.read_bytes().decode(detected)

    assert "城市" in text
    assert "北京" in text


def test_detect_encoding_prefers_utf8_for_ascii(tmp_path: Path):
    path = tmp_path / "ascii.csv"
    path.write_bytes(b"city,sales\nBeijing,1200\n")

    assert _detect_encoding(str(path)) == "utf-8"


def test_utf16_without_bom(tmp_path: Path):
    path = tmp_path / "utf16.csv"
    path.write_bytes(_SAMPLE.encode("utf-16-le"))

    detected = _detect_encoding(str(path))

    assert detected == "utf-16-le"
    assert "城市" in path.read_bytes().decode(detected)


def test_delimiter_detection_uses_detected_encoding(tmp_path: Path):
    path = tmp_path / "semicolon.csv"
    path.write_bytes("城市;销售额\n北京;1200\n".encode("gbk"))

    assert _detect_delimiter(str(path), ",") == ";"


def test_file_reader_reads_gbk_csv(tmp_path: Path):
    path = tmp_path / "sales.csv"
    path.write_bytes(_SAMPLE.encode("gbk"))

    tables = FileReader.read(str(path))

    df = tables[0].df
    assert list(df.columns) == ["城市", "销售额"]
    assert df["城市"].tolist() == ["北京", "上海"]
    assert df["销售额"].tolist() == [1200, 1300]


def test_file_reader_strips_utf8_bom_from_columns(tmp_path: Path):
    path = tmp_path / "bom.csv"
    path.write_bytes(_SAMPLE.encode("utf-8-sig"))

    df = FileReader.read(str(path))[0].df

    assert list(df.columns) == ["城市", "销售额"]
    assert df["城市"].tolist() == ["北京", "上海"]


async def test_ingest_gbk_csv(tmp_path: Path, monkeypatch):
    """完整接入链路：GBK CSV -> 正确列名 -> 数值归一化。"""
    from service.data_ingestion import DataSource, ingest

    monkeypatch.setenv("TEMP_DATASETS_DIR", str(tmp_path / "datasets"))
    path = tmp_path / "sales.csv"
    # 用带千分位的文本，同时验证编码 + 数值归一化
    path.write_bytes('城市,销售额\n北京,"1,200"\n上海,"1,300"\n'.encode("gbk"))

    profile = await ingest(DataSource(kind="file", path=str(path), name="sales"))

    assert [col["name"] for col in profile.schema] == ["城市", "销售额"]
    assert profile.preview[0]["城市"] == "北京"
    assert profile.preview[0]["销售额"] == 1200
