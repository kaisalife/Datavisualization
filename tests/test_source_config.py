"""数据源表单解析/校验回归。

`/api/data-profile` 与 `/api/generate-chart-with-prompt` 共用
`api/source_config.py`；这里同时覆盖纯函数与两个接口的早失败行为。
"""
from __future__ import annotations

import json

import pytest

from api.source_config import (
    normalize_db_type,
    parse_json_object,
    validate_source_configs,
)


def test_parse_json_object_handles_empty():
    assert parse_json_object("", "db_config") is None
    assert parse_json_object("   ", "db_config") is None
    assert parse_json_object(None, "db_config") is None


def test_parse_json_object_rejects_invalid():
    with pytest.raises(ValueError, match="db_config 不是合法 JSON"):
        parse_json_object("{bad", "db_config")
    with pytest.raises(ValueError, match="必须是 JSON 对象"):
        parse_json_object("[1, 2]", "db_config")


def test_normalize_db_type_trims_and_aliases():
    assert normalize_db_type({"type": " MySQL "}) == "mysql"
    assert normalize_db_type({"type": "Postgres"}) == "postgresql"
    assert normalize_db_type({"type": "SQLite"}) == "sqlite"
    assert normalize_db_type({}) == "postgresql"
    assert normalize_db_type(None) is None


def test_validate_source_configs_accepts_valid():
    assert validate_source_configs({"type": "SQLite", "database": "x.db"}, None) == "sqlite"
    assert validate_source_configs(None, {"url": "https://example.com/x"}) is None
    assert validate_source_configs(None, None) is None


def test_validate_source_configs_rejects_bad():
    with pytest.raises(ValueError, match="不支持的数据库类型: oracle"):
        validate_source_configs({"type": "Oracle"}, None)
    with pytest.raises(ValueError, match="database/path"):
        validate_source_configs({"type": "sqlite"}, None)
    with pytest.raises(ValueError, match="url 或 api_type"):
        validate_source_configs(None, {"method": "GET"})


def test_chart_endpoint_rejects_invalid_source_before_task(client):
    resp = client.post("/api/generate-chart-with-prompt", data={"user_prompt": "画图"})
    assert resp.status_code == 400
    assert "必须提供" in resp.get_json()["detail"]

    resp = client.post(
        "/api/generate-chart-with-prompt",
        data={"user_prompt": "画图", "db_config": "{bad"},
    )
    assert resp.status_code == 400
    assert "db_config 不是合法 JSON" in resp.get_json()["detail"]

    resp = client.post(
        "/api/generate-chart-with-prompt",
        data={"user_prompt": "画图", "db_config": json.dumps({"type": "Oracle"})},
    )
    assert resp.status_code == 400
    assert "不支持的数据库类型" in resp.get_json()["detail"]

    resp = client.post(
        "/api/generate-chart-with-prompt",
        data={"user_prompt": "画图", "api_config": json.dumps({"method": "GET"})},
    )
    assert resp.status_code == 400
    assert "url 或 api_type" in resp.get_json()["detail"]
