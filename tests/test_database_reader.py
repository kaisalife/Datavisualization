"""DatabaseReader 表名引用与 SQLite 读取回归（不联网）。"""
from __future__ import annotations

import sqlite3

import pytest

from service.data_ingestion.readers.database_reader import DatabaseReader, _quote_identifier


def _make_sqlite(tmp_path, table_name: str):
    db_path = tmp_path / "data.db"
    conn = sqlite3.connect(db_path)
    quoted = _quote_identifier(table_name, "sqlite")
    conn.execute(f"CREATE TABLE {quoted} (城市 TEXT, 销售额 INTEGER)")
    conn.execute(f"INSERT INTO {quoted} VALUES ('北京', 1200)")
    conn.execute(f"INSERT INTO {quoted} VALUES ('上海', 1500)")
    conn.commit()
    conn.close()
    return db_path


def test_sqlite_reads_normal_table(tmp_path):
    db_path = _make_sqlite(tmp_path, "sales")

    tables = DatabaseReader.read({"database": str(db_path)}, "sqlite", tables=["sales"])

    assert len(tables) == 1
    assert tables[0].df.to_dict("records") == [
        {"城市": "北京", "销售额": 1200},
        {"城市": "上海", "销售额": 1500},
    ]


def test_sqlite_accepts_uppercase_type_from_frontend(tmp_path):
    db_path = _make_sqlite(tmp_path, "sales")

    tables = DatabaseReader.read(
        {"database": str(db_path)}, "SQLite", tables=["sales"]
    )

    assert len(tables) == 1
    assert tables[0].df["销售额"].tolist() == [1200, 1500]


def test_sqlite_table_name_with_double_quote(tmp_path):
    db_path = _make_sqlite(tmp_path, 'sales"2024')

    tables = DatabaseReader.read(
        {"database": str(db_path)}, "sqlite", tables=['sales"2024']
    )

    assert len(tables) == 1
    assert tables[0].df["销售额"].tolist() == [1200, 1500]


def test_sqlite_table_name_with_space(tmp_path):
    db_path = _make_sqlite(tmp_path, "2024 sales")

    tables = DatabaseReader.read(
        {"database": str(db_path)}, "sqlite", tables=["2024 sales"]
    )

    assert len(tables) == 1
    assert len(tables[0].df) == 2


def test_sqlite_query_mode(tmp_path):
    db_path = _make_sqlite(tmp_path, "sales")

    tables = DatabaseReader.read(
        {"database": str(db_path)},
        "sqlite",
        query='SELECT "城市", "销售额" FROM "sales" WHERE "销售额" > 1300',
    )

    assert len(tables) == 1
    assert tables[0].df.to_dict("records") == [{"城市": "上海", "销售额": 1500}]


def test_quote_identifier_escapes_by_dialect():
    assert _quote_identifier('a"b', "postgresql") == '"a""b"'
    assert _quote_identifier("a`b", "mysql") == "`a``b`"
    assert _quote_identifier("a`b", "postgresql") == '"a`b"'


def test_quote_identifier_accepts_frontend_case():
    assert _quote_identifier("a`b", "MySQL") == "`a``b`"
    assert _quote_identifier('a"b', "PostgreSQL") == '"a""b"'


def test_build_url_escapes_special_characters_in_credentials():
    url = DatabaseReader._build_url(
        {
            "host": "db.example.com",
            "port": "5433",
            "database": "my db",
            "user": "u@ser",
            "password": "p@ss:word/?#",
        },
        "postgresql",
    )

    assert url.drivername == "postgresql+psycopg2"
    assert url.username == "u@ser"
    assert url.password == "p@ss:word/?#"
    assert url.host == "db.example.com"
    assert url.port == 5433
    assert url.database == "my db"


def test_build_url_accepts_frontend_case_and_postgres_alias():
    mysql_url = DatabaseReader._build_url({"database": "d"}, "MySQL")
    assert mysql_url.drivername == "mysql+pymysql"
    assert mysql_url.port == 3306

    pg_url = DatabaseReader._build_url({"database": "d"}, "Postgres")
    assert pg_url.drivername == "postgresql+psycopg2"
    assert pg_url.port == 5432


def test_build_url_uses_default_port_for_invalid_value():
    url = DatabaseReader._build_url({"database": "d", "port": "not-a-port"}, "mysql")

    assert url.drivername == "mysql+pymysql"
    assert url.port == 3306


def test_build_url_rejects_unknown_dialect():
    with pytest.raises(ValueError, match="不支持的数据库类型"):
        DatabaseReader._build_url({}, "oracle")


def test_unsupported_database_type():
    with pytest.raises(ValueError, match="不支持的数据库类型"):
        DatabaseReader.read({}, "oracle", tables=["t"])
