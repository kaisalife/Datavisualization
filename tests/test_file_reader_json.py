"""FileReader 的 JSON / JSONL 兼容性回归（不联网）。"""
from __future__ import annotations

import json

import pandas as pd
import pytest

from service.data_ingestion.readers.file_reader import FileReader


def _read(tmp_path, name: str, content: str, encoding: str = "utf-8") -> pd.DataFrame:
    path = tmp_path / name
    path.write_text(content, encoding=encoding)
    return FileReader.read(str(path))[0].df


def test_json_single_object_becomes_one_row(tmp_path):
    df = _read(tmp_path, "one.json", json.dumps({"城市": "北京", "销售额": 1200}, ensure_ascii=False))
    assert list(df.columns) == ["城市", "销售额"]
    assert df.to_dict("records") == [{"城市": "北京", "销售额": 1200}]


def test_json_pretty_printed_array_is_not_treated_as_jsonl(tmp_path):
    payload = [
        {"城市": "北京", "销售额": 1200},
        {"城市": "上海", "销售额": 1500},
    ]
    df = _read(tmp_path, "array.json", json.dumps(payload, ensure_ascii=False, indent=2))
    assert len(df) == 2
    assert list(df["城市"]) == ["北京", "上海"]


def test_json_array_of_arrays_keeps_values(tmp_path):
    df = _read(tmp_path, "matrix.json", "[[1, 2], [3, 4]]")
    assert df.shape == (2, 2)
    assert df.iloc[1].tolist() == [3, 4]


def test_json_object_of_columns_becomes_wide_table(tmp_path):
    df = _read(
        tmp_path,
        "columns.json",
        json.dumps({"城市": ["北京", "上海"], "销售额": [1200, 1500]}, ensure_ascii=False),
    )
    assert df.shape == (2, 2)
    assert list(df["城市"]) == ["北京", "上海"]


def test_json_nested_object_is_flattened(tmp_path):
    df = _read(
        tmp_path,
        "nested.json",
        json.dumps([{"城市": "北京", "指标": {"销售额": 1200, "利润": 300}}], ensure_ascii=False),
    )
    assert "指标.销售额" in df.columns
    assert df.iloc[0]["指标.销售额"] == 1200


def test_jsonl_and_ndjson_are_read_line_by_line(tmp_path):
    text = '{"城市": "北京", "销售额": 1200}\n\n{"城市": "上海", "销售额": 1500}\n'
    for name in ("data.jsonl", "data.ndjson"):
        df = _read(tmp_path, name, text)
        assert len(df) == 2
        assert list(df["城市"]) == ["北京", "上海"]


def test_json_with_concatenated_objects_falls_back_to_jsonl(tmp_path):
    text = '{"城市": "北京", "销售额": 1200}\n{"城市": "上海", "销售额": 1500}\n'
    df = _read(tmp_path, "actually.jsonl.json", text)
    assert len(df) == 2
    assert list(df["城市"]) == ["北京", "上海"]


def test_json_with_utf8_bom(tmp_path):
    df = _read(
        tmp_path,
        "bom.json",
        json.dumps([{"城市": "北京", "销售额": 1200}], ensure_ascii=False),
        encoding="utf-8-sig",
    )
    assert df.iloc[0]["城市"] == "北京"


def test_invalid_json_reports_file_name(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text('{"城市": "北京",', encoding="utf-8")
    with pytest.raises(ValueError, match="broken.json"):
        FileReader.read(str(path))


def test_invalid_jsonl_reports_line_number(tmp_path):
    path = tmp_path / "broken.jsonl"
    path.write_text('{"城市": "北京"}\n{not json}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="第 2 行"):
        FileReader.read(str(path))
