"""数据库「测试连接 / 列出表」回归（SQLite，不联网）。

覆盖：
- DatabaseReader.list_tables 返回排序后的真实表名；
- sqlite 路径写错时报错且**不会**创建空库；
- 不支持的数据库类型；
- POST /api/data-source/db-tables 的表单 / JSON body 两种入参与错误码。
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from service.data_ingestion.readers.database_reader import DatabaseReader


def _make_sqlite(tmp_path, tables=("sales", "users")):
    db_path = tmp_path / "data.db"
    conn = sqlite3.connect(db_path)
    for name in tables:
        conn.execute(f'CREATE TABLE "{name}" (id INTEGER, value INTEGER)')
        conn.execute(f'INSERT INTO "{name}" VALUES (1, 100)')
    conn.commit()
    conn.close()
    return db_path


def test_list_tables_returns_sorted_real_tables(tmp_path):
    db_path = _make_sqlite(tmp_path, tables=("sales", "users"))

    tables = DatabaseReader.list_tables({"database": str(db_path)}, "SQLite")

    assert tables == ["sales", "users"]


def test_list_tables_accepts_path_key(tmp_path):
    db_path = _make_sqlite(tmp_path, tables=("sales",))

    assert DatabaseReader.list_tables({"path": str(db_path)}, "sqlite") == ["sales"]


def test_list_tables_missing_file_does_not_create_empty_db(tmp_path):
    db_path = tmp_path / "typo.db"

    with pytest.raises(ValueError, match="sqlite 数据库文件不存在"):
        DatabaseReader.list_tables({"database": str(db_path)}, "sqlite")

    # sqlite3.connect 会自动建库，必须确认这里没有留下空文件
    assert not db_path.exists()


def test_read_missing_sqlite_file_fails_cleanly(tmp_path):
    db_path = tmp_path / "typo.db"

    with pytest.raises(ValueError, match="sqlite 数据库文件不存在"):
        DatabaseReader.read({"database": str(db_path)}, "sqlite", tables=["sales"])

    assert not db_path.exists()


def test_list_tables_rejects_unsupported_type(tmp_path):
    with pytest.raises(ValueError, match="不支持的数据库类型"):
        DatabaseReader.list_tables({"database": "x.db"}, "oracle")


def test_db_tables_endpoint_accepts_form(client, tmp_path):
    db_path = _make_sqlite(tmp_path)

    resp = client.post(
        "/api/data-source/db-tables",
        data={"db_config": json.dumps({"type": "SQLite", "database": str(db_path)})},
    )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["db_type"] == "sqlite"
    assert body["count"] == 2
    assert body["tables"] == ["sales", "users"]


def test_db_tables_endpoint_accepts_json_body(client, tmp_path):
    db_path = _make_sqlite(tmp_path, tables=("sales",))

    resp = client.post(
        "/api/data-source/db-tables",
        json={"db_config": {"type": "sqlite", "database": str(db_path)}},
    )

    assert resp.status_code == 200
    assert resp.get_json()["tables"] == ["sales"]


def test_db_tables_endpoint_rejects_bad_config(client, tmp_path):
    resp = client.post("/api/data-source/db-tables", data={})
    assert resp.status_code == 400
    assert "db_config" in resp.get_json()["detail"]

    resp = client.post(
        "/api/data-source/db-tables",
        data={"db_config": json.dumps({"type": "Oracle"})},
    )
    assert resp.status_code == 400
    assert "不支持的数据库类型" in resp.get_json()["detail"]

    resp = client.post(
        "/api/data-source/db-tables",
        data={"db_config": "{bad"},
    )
    assert resp.status_code == 400
    assert "不是合法 JSON" in resp.get_json()["detail"]

    resp = client.post(
        "/api/data-source/db-tables",
        data={
            "db_config": json.dumps(
                {"type": "sqlite", "database": str(tmp_path / "missing.db")}
            )
        },
    )
    assert resp.status_code == 400
    assert "文件不存在" in resp.get_json()["detail"]
