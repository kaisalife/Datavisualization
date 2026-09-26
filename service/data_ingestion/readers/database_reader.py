"""数据库 Reader（v4）。

通过原生 DB 客户端（sqlalchemy / sqlite3）把表/查询读入 DataFrame，
返回 list[RawTable]（不再依赖 DuckDB ATTACH）。

两种模式:
1. 显式 SQL: 用户提供 SQL 查询 -> 读入 DataFrame
2. 表名模式: 用户指定表名 -> 读入 DataFrame
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd

from service.data_ingestion.models import RawTable, safe_table_name
from service.observability import get_logger

logger = get_logger(__name__)


class DatabaseReader:
    """从数据库读取数据为 DataFrame。"""

    @staticmethod
    def can_handle(db_type: str) -> bool:
        return (db_type or "").lower() in {"postgresql", "mysql", "sqlite"}

    @staticmethod
    def _build_url(db_config: dict, db_type: str) -> str:
        """构建 sqlalchemy 连接串（postgres/mysql 用）。"""
        host = db_config.get("host", "localhost")
        port = db_config.get("port", 5432 if db_type == "postgresql" else 3306)
        database = db_config.get("database", "")
        user = db_config.get("user", db_config.get("username", ""))
        password = db_config.get("password", db_config.get("pwd", ""))
        if db_type == "postgresql":
            return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{database}"
        if db_type == "mysql":
            return f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}"
        return ""

    @staticmethod
    def _make_engine(db_config: dict, db_type: str):
        """构造 read_sql 用的连接对象。

        sqlite 用标准库连接；postgres/mysql 用 sqlalchemy（需安装对应驱动）。
        """
        if db_type == "sqlite":
            path = db_config.get("database", db_config.get("path", ""))
            if not path:
                raise ValueError("sqlite 数据库必须提供 database/path 配置")
            return sqlite3.connect(path)

        url = DatabaseReader._build_url(db_config, db_type)
        try:
            from sqlalchemy import create_engine
            return create_engine(url)
        except ImportError:
            raise ImportError(
                "database_reader 需要 sqlalchemy。请运行: pip install sqlalchemy"
                + (" psycopg2-binary" if db_type == "postgresql" else " pymysql")
            )

    @staticmethod
    def read(
        db_config: dict,
        db_type: str,
        table_name: str | None = None,
        query: str | None = None,
        tables: list[str] | None = None,
    ) -> list[RawTable]:
        """连接数据库并把表/查询读入 DataFrame。

        Args:
            db_config: 数据库连接配置
            db_type: "postgresql" | "mysql" | "sqlite"
            table_name: 目标表名 (可选)
            query: 自定义 SQL 查询 (优先)
            tables: 要读取的表名列表

        Returns:
            list[RawTable]（多表时每个一条）
        """
        if not DatabaseReader.can_handle(db_type):
            raise ValueError(f"不支持的数据库类型: {db_type}")

        conn = DatabaseReader._make_engine(db_config, db_type)
        source_path = f"{db_type}://{_mask_conn(db_config)}"
        try:
            if query:
                name = safe_table_name(table_name or "query_result")
                df = pd.read_sql(query, conn)
                return [RawTable(name=name, df=df, source_kind="database", source_path=source_path)]

            target_tables = tables or DatabaseReader._list_tables(conn, db_type)
            if not target_tables:
                raise ValueError("数据库中未找到表")

            raw_tables = []
            for i, tbl in enumerate(target_tables):
                name = safe_table_name(table_name if i == 0 else tbl)
                df = pd.read_sql(f'SELECT * FROM "{tbl}"', conn)
                raw_tables.append(RawTable(
                    name=name, df=df, source_kind="database", source_path=f"{source_path}#{tbl}"
                ))
            return raw_tables
        finally:
            try:
                conn.close()
            except Exception:
                pass

    @staticmethod
    def _list_tables(conn, db_type: str) -> list[str]:
        """列出库中的表名（含 sqlite 兼容）。"""
        try:
            from sqlalchemy import inspect
            inspector = inspect(conn)
            return [t for t in inspector.get_table_names() if not t.startswith("sqlite_")]
        except Exception:
            try:
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
                return [r[0] for r in cursor.fetchall() if not r[0].startswith("sqlite_")]
            except Exception as e:
                logger.warning("_list_tables 自动发现失败", db_type=db_type, error=str(e))
                return []


def _mask_conn(db_config: dict) -> str:
    """连接信息脱敏（不打日志暴露密码）。"""
    safe = {k: v for k, v in db_config.items() if k not in ("password", "pwd", "api_key")}
    return str(safe)