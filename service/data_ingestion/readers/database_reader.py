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
from service.data_ingestion.sql_safety import ensure_read_only
from service.observability import get_logger

logger = get_logger(__name__)


_DB_TYPE_ALIASES = {
    "postgres": "postgresql",
    "postgresql": "postgresql",
    "mysql": "mysql",
    "sqlite": "sqlite",
}


def _normalize_db_type(db_type: str) -> str:
    """统一数据库类型大小写与常见别名（前端默认发 "MySQL" / "PostgreSQL"）。"""
    text = str(db_type or "").strip().lower()
    return _DB_TYPE_ALIASES.get(text, text)


def _quote_identifier(name: str, db_type: str) -> str:
    """按数据库方言引用表名，转义标识符里的引号（防拼接出非法 SQL）。"""
    text = str(name)
    if _normalize_db_type(db_type) == "mysql":
        return "`" + text.replace("`", "``") + "`"
    return '"' + text.replace('"', '""') + '"'


class DatabaseReader:
    """从数据库读取数据为 DataFrame。"""

    @staticmethod
    def can_handle(db_type: str) -> bool:
        return _normalize_db_type(db_type) in {"postgresql", "mysql", "sqlite"}

    @staticmethod
    def _build_url(db_config: dict, db_type: str):
        """构建 sqlalchemy URL（postgres/mysql 用），自动转义账号密码里的特殊字符。"""
        from sqlalchemy.engine import URL

        db_type = _normalize_db_type(db_type)
        default_port = 5432 if db_type == "postgresql" else 3306
        host = str(db_config.get("host") or "localhost")
        try:
            port = int(db_config.get("port") or default_port)
        except (TypeError, ValueError):
            port = default_port
        database = str(db_config.get("database") or "") or None
        user = str(db_config.get("user", db_config.get("username", "")) or "") or None
        password = str(db_config.get("password", db_config.get("pwd", "")) or "") or None

        if db_type == "postgresql":
            driver = "postgresql+psycopg2"
        elif db_type == "mysql":
            driver = "mysql+pymysql"
        else:
            raise ValueError(f"不支持的数据库类型: {db_type}")
        return URL.create(
            driver,
            username=user,
            password=password,
            host=host,
            port=port,
            database=database,
        )

    @staticmethod
    def _make_engine(db_config: dict, db_type: str, connect_timeout: int | None = None):
        """构造 read_sql 用的连接对象。

        sqlite 用标准库连接；postgres/mysql 用 sqlalchemy（需安装对应驱动）。

        Args:
            db_config: 数据库连接配置
            db_type: 数据库类型（大小写/别名由内部归一化）
            connect_timeout: 建立连接的超时秒数；None 时用驱动默认值

        Raises:
            ValueError: sqlite 未提供路径，或路径不存在。sqlite3.connect 会自动
                创建空库，提前拦截可以避免把写错的路径当成一个空数据库。
        """
        db_type = _normalize_db_type(db_type)
        if db_type == "sqlite":
            path = str(db_config.get("database", db_config.get("path", "")) or "").strip()
            if not path:
                raise ValueError("sqlite 数据库必须提供 database/path 配置")
            if path != ":memory:":
                expanded = Path(path).expanduser()
                if not expanded.is_file():
                    raise ValueError(f"sqlite 数据库文件不存在: {path}")
                path = str(expanded)
            return sqlite3.connect(path)

        try:
            from sqlalchemy import create_engine
            url = DatabaseReader._build_url(db_config, db_type)
            connect_args = {}
            if connect_timeout:
                # psycopg2 / pymysql 都用 connect_timeout（秒）
                connect_args["connect_timeout"] = int(connect_timeout)
            return create_engine(url, connect_args=connect_args)
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
        db_type = _normalize_db_type(db_type)
        if not DatabaseReader.can_handle(db_type):
            raise ValueError(f"不支持的数据库类型: {db_type}")

        # 自定义 SQL 直接交给驱动执行，先挡住写操作 / 多语句（误操作与注入）
        query = str(query or "").strip()
        if query:
            ensure_read_only(query)

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
                # 未显式指定表名时，第一张表也应使用真实表名，而不是兜底的 "data"
                name = safe_table_name(table_name if i == 0 and table_name else tbl)
                quoted = _quote_identifier(tbl, db_type)
                df = pd.read_sql(f"SELECT * FROM {quoted}", conn)
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
    def list_tables(
        db_config: dict, db_type: str, connect_timeout: int = 5
    ) -> list[str]:
        """连接数据库并列出所有表（供「测试连接 / 列出表」使用）。

        与自动发现不同，这里连接失败会抛异常而不是返回空列表，
        让前端能区分「连不上」和「库是空的」。

        Args:
            db_config: 数据库连接配置
            db_type: 数据库类型（大小写/别名由内部归一化）
            connect_timeout: 建立连接的超时秒数

        Returns:
            排序后的表名列表（不含 sqlite 内部表）

        Raises:
            ValueError: 数据库类型不支持 / sqlite 文件不存在
            Exception: 连接失败（驱动原始异常）
        """
        db_type = _normalize_db_type(db_type)
        if not DatabaseReader.can_handle(db_type):
            raise ValueError(f"不支持的数据库类型: {db_type}")

        conn = DatabaseReader._make_engine(
            db_config, db_type, connect_timeout=connect_timeout
        )
        try:
            return sorted(DatabaseReader._list_tables(conn, db_type, strict=True))
        finally:
            try:
                conn.close()
            except Exception:
                pass

    @staticmethod
    def _list_tables(conn, db_type: str, strict: bool = False) -> list[str]:
        """列出库中的表名（含 sqlite 兼容）。

        Args:
            conn: sqlite3 连接或 sqlalchemy Engine
            db_type: 数据库类型
            strict: True 时把连接/读取失败抛给调用方；False（默认）时只记日志，
                避免影响「自动发现全部表」的既有读取流程
        """
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
                if strict:
                    raise
                logger.warning("_list_tables 自动发现失败", db_type=db_type, error=str(e))
                return []


def _mask_conn(db_config: dict) -> str:
    """连接信息脱敏（不打日志暴露密码）。"""
    safe = {k: v for k, v in db_config.items() if k not in ("password", "pwd", "api_key")}
    return str(safe)