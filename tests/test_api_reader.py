"""API Reader 的 JSON 形状归一化回归（不发起网络请求）。"""
from __future__ import annotations

import service.data_ingestion.readers.api_reader as api_reader
from service.data_ingestion.readers.api_reader import ApiReader


def _read_with(monkeypatch, payload):
    monkeypatch.setattr(api_reader, "_fetch_json", lambda *args, **kwargs: payload)
    return ApiReader.read(url="https://example.com/data", table_name="api_data")


def test_api_list_of_nested_objects_is_flattened(monkeypatch):
    payload = [
        {"city": "北京", "metrics": {"sales": 1200, "profit": 300}},
        {"city": "上海", "metrics": {"sales": 1500, "profit": 360}},
    ]

    tables = _read_with(monkeypatch, payload)

    assert len(tables) == 1
    df = tables[0].df
    assert "metrics.sales" in df.columns
    assert df["metrics.sales"].tolist() == [1200, 1500]


def test_api_wrapped_data_array(monkeypatch):
    payload = {
        "code": 0,
        "data": [
            {"city": "北京", "sales": 1200},
            {"city": "上海", "sales": 1500},
        ],
    }

    df = _read_with(monkeypatch, payload)[0].df

    assert df.to_dict("records") == [
        {"city": "北京", "sales": 1200},
        {"city": "上海", "sales": 1500},
    ]


def test_api_single_object_becomes_one_row(monkeypatch):
    payload = {"city": "北京", "sales": 1200}

    df = _read_with(monkeypatch, payload)[0].df

    assert len(df) == 1
    assert df.iloc[0]["city"] == "北京"


def test_api_object_of_columns_becomes_wide_table(monkeypatch):
    payload = {"city": ["北京", "上海"], "sales": [1200, 1500]}

    df = _read_with(monkeypatch, payload)[0].df

    assert df.shape == (2, 2)
    assert df["sales"].tolist() == [1200, 1500]


def test_api_scalar_becomes_value_column(monkeypatch):
    df = _read_with(monkeypatch, 42)[0].df

    assert df.to_dict("records") == [{"value": 42}]


def test_api_post_passes_body_and_headers(monkeypatch):
    captured = {}

    def fake_fetch(url, method="GET", headers=None, body=None, timeout=30):
        captured.update(url=url, method=method, headers=headers, body=body)
        return [{"city": "北京", "sales": 1200}]

    monkeypatch.setattr(api_reader, "_fetch_json", fake_fetch)

    ApiReader.read(
        url="https://example.com/data",
        method="POST",
        headers={"Authorization": "Bearer token"},
        body='{"month": 1}',
    )

    assert captured["method"] == "POST"
    assert captured["headers"] == {"Authorization": "Bearer token"}
    assert captured["body"] == b'{"month": 1}'
