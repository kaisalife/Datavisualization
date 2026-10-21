"""自定义 SQL 只读校验回归。

覆盖纯函数、DatabaseReader 执行前拦截，以及两个接口的早失败行为。
用 SQLite 夹具验证「被拒绝的 DROP 确实没有执行」。
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from api.source_config import validate_source_configs
from service.data_ingestion.readers.database_reader import DatabaseReader
from service.data_ingestion.sql_safety import ensure_read_only


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM sales",
        "  select 1  ",
        "select 1;",
        "select ';' as sep",
        'select "a;b" from sales',
        "select 1 -- comment; drop table sales",
        "/* drop table sales */ select 1",
        "with t as (select 1 as a) select * from t",
        "WITH t AS (SELECT 1) VALUES (1)",
        "EXPLAIN select 1",
        "SHOW TABLES",
        "DESCRIBE sales",
        "VALUES (1), (2)",
    ],
)
def test_allows_read_only_queries(sql):
    ensure_read_only(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE sales",
        "delete from sales",
        "UPDATE sales SET amount = 0",
        "insert into sales values (1)",
        "create table t (id int)",
        "truncate table sales",
        "select 1; drop table sales",
        "select 1;select 2",
        "with t as (select 1) delete from sales",
        "with t as (select 1)",
        "PRAGMA journal_mode = WAL",
        "   ",
        "-- only a comment",
        "/* drop table sales */",
    ],
)
def test_rejects_write_or_multi_statement(sql):
    with pytest.raises(ValueError, match="只读|不能为空"):
        ensure_read_only(sql)


def _make_sqlite(tmp_path):
    db_path = tmp_path / "data.db"
    conn = sqlite3.connect(db_path)
    conn.execute('CREATE TABLE "sales" (id INTEGER, amount INTEGER)')
    conn.execute('INSERT INTO "sales" VALUES (1, 100)')
    conn.commit()
    conn.close()
    return db_path


def test_database_reader_blocks_drop_before_execution(tmp_path):
    db_path = _make_sqlite(tmp_path)

    with pytest.raises(ValueError, match="只读"):
        DatabaseReader.read(
            {"database": str(db_path)}, "sqlite", query='DROP TABLE "sales"'
        )

    # 表必须还在：证明校验发生在驱动执行之前
    assert DatabaseReader.list_tables({"database": str(db_path)}, "sqlite") == ["sales"]


def test_database_reader_still_runs_read_query(tmp_path):
    db_path = _make_sqlite(tmp_path)

    tables = DatabaseReader.read(
        {"database": str(db_path)},
        "sqlite",
        query="select * from sales where amount > 0",
    )

    assert tables[0].df["amount"].tolist() == [100]


def test_validate_source_configs_rejects_write_query():
    with pytest.raises(ValueError, match="只读"):
        validate_source_configs(
            {"type": "sqlite", "database": "x.db", "query": "drop table sales"}, None
        )


def test_validate_source_configs_drops_blank_query():
    cfg = {"type": "sqlite", "database": "x.db", "query": "   "}
    assert validate_source_configs(cfg, None) == "sqlite"
    assert "query" not in cfg


def test_chart_endpoint_rejects_write_query_before_task(client, tmp_path):
    db_path = _make_sqlite(tmp_path)
    resp = client.post(
        "/api/generate-chart-with-prompt",
        data={
            "user_prompt": "画图",
            "db_config": json.dumps(
                {"type": "sqlite", "database": str(db_path), "query": "DROP TABLE sales"}
            ),
        },
    )
    assert resp.status_code == 400
    assert "只读" in resp.get_json()["detail"]


def test_data_profile_rejects_write_query(client, tmp_path):
    db_path = _make_sqlite(tmp_path)
    resp = client.post(
        "/api/data-profile",
        data={
            "db_config": json.dumps(
                {
                    "type": "sqlite",
                    "database": str(db_path),
                    "query": "select 1; drop table sales",
                }
            )
        },
    )
    assert resp.status_code == 400
    assert "不能包含多条语句" in resp.get_json()["detail"]
