"""SQL 数据库驱动：sqlalchemy 通用实现。

支持：sqlite / mysql / postgresql / mssql / oracle
凭据从 db_config 组装成 URL，不写入日志。
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import quote_plus

import pandas as pd
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from service.viz_data.db_drivers.base import DBDriver, DBIntrospection, TableIntrospection


# 仅允许 SELECT/SHOW/DESC/EXPLAIN（首个非注释关键字）
_ALLOWED_STARTERS = re.compile(r"^(select|show|desc|describe|explain|with)\b", re.IGNORECASE)

# 明确禁止的破坏性关键字（防御性检查）
_DENIED_KEYWORDS = re.compile(
    r"\b(drop|delete|update|insert|create|alter|truncate|grant|revoke|call|exec|execute)\b",
    re.IGNORECASE,
)


class SqlDriverError(Exception):
    """SQL 驱动错误。"""


class SqlDriver(DBDriver):
    """sqlalchemy 通用 SQL 驱动。"""

    _DRIVER_MAP = {
        "sqlite": "sqlite",
        "mysql": "mysql+pymysql",
        "postgresql": "postgresql+psycopg2",
        "postgres": "postgresql+psycopg2",
        "mssql": "mssql+pyodbc",
        "oracle": "oracle+oracledb",
    }

    _DEFAULT_PORT = {
        "mysql": 3306,
        "postgresql": 5432,
        "postgres": 5432,
        "mssql": 1433,
        "oracle": 1521,
    }

    def __init__(self, db_config: dict):
        self.db_config = db_config
        self.db_type = str(db_config.get("db_type", "")).lower()
        if self.db_type not in self._DRIVER_MAP:
            raise SqlDriverError(f"不支持的 db_type: {self.db_type}")

        self._engine: Optional[Engine] = None
        self._url = self._build_url()

    # ------ 连接管理 ------

    def _build_url(self) -> str:
        """从 db_config 组装 sqlalchemy URL。"""
        cfg = self.db_config
        dialect = self._DRIVER_MAP[self.db_type]

        # sqlite 特殊路径处理
        if self.db_type == "sqlite":
            path = cfg.get("database", "")
            if not path:
                raise SqlDriverError("sqlite 需要 database 字段（文件路径或 :memory:）")
            return f"sqlite:///{path}"

        user = quote_plus(str(cfg.get("user", "")))
        password = quote_plus(str(cfg.get("password", "")))
        host = cfg.get("host", "localhost")
        port = cfg.get("port") or self._DEFAULT_PORT.get(self.db_type, "")
        database = cfg.get("database", "")

        auth = f"{user}:{password}@" if user else ""
        port_part = f":{port}" if port else ""
        return f"{dialect}://{auth}{host}{port_part}/{database}"

    def _get_engine(self) -> Engine:
        if self._engine is None:
            self._engine = create_engine(self._url, pool_pre_ping=True, future=True)
        return self._engine

    def close(self) -> None:
        if self._engine is not None:
            try:
                self._engine.dispose()
            except Exception:
                pass
            self._engine = None

    # ------ Introspect ------

    def introspect(self, tables: Optional[list[str]] = None,
                   sample_rows: int = 3) -> DBIntrospection:
        engine = self._get_engine()
        inspector = inspect(engine)

        all_tables = inspector.get_table_names()
        target_tables = tables if tables else all_tables

        result_tables = []
        for tname in target_tables:
            if tname not in all_tables:
                continue

            cols_info = []
            pk_cols = set(inspector.get_pk_constraint(tname).get("constrained_columns", []))
            fk_info = {}
            for fk in inspector.get_foreign_keys(tname):
                for col, ref_col in zip(fk.get("constrained_columns", []),
                                        fk.get("referred_columns", [])):
                    fk_info[col] = f"{fk.get('referred_table')}.{ref_col}"

            for col in inspector.get_columns(tname):
                cols_info.append({
                    "name": col["name"],
                    "dtype": str(col["type"]).lower(),
                    "nullable": col.get("nullable", True),
                    "primary_key": col["name"] in pk_cols,
                    "foreign_key": fk_info.get(col["name"]),
                })

            # 样例行 + 行数
            row_count = None
            sample = []
            try:
                with engine.connect() as conn:
                    row_count_result = conn.execute(text(f"SELECT COUNT(*) FROM {tname}"))
                    row_count = row_count_result.scalar()

                    if sample_rows > 0:
                        sample_result = conn.execute(
                            text(f"SELECT * FROM {tname} LIMIT {int(sample_rows)}")
                        )
                        for row in sample_result:
                            sample.append(list(row))
            except Exception as e:
                # 部分数据库 SELECT LIMIT 语法不同，尽力而为
                print(f"⚠️ 样本行/行数查询失败 {tname}: {e}")

            result_tables.append(TableIntrospection(
                name=tname,
                row_count=row_count,
                columns=cols_info,
                sample_rows=sample,
            ))

        return DBIntrospection(
            db_type=self.db_type,
            database=str(self.db_config.get("database", "")),
            tables=result_tables,
        )

    # ------ 查询执行 ------

    def execute_query(self, sql: str, limit: int = 100000) -> pd.DataFrame:
        """执行查询。做基础安全检查。"""
        cleaned = _strip_sql_comments(sql).strip().rstrip(";").strip()
        if not cleaned:
            raise SqlDriverError("SQL 为空")
        if not _ALLOWED_STARTERS.match(cleaned):
            raise SqlDriverError(f"仅允许 SELECT/SHOW/DESC/EXPLAIN/WITH 开头: {cleaned[:60]}")
        if _DENIED_KEYWORDS.search(cleaned):
            raise SqlDriverError(f"SQL 包含禁止的关键字（DROP/DELETE/UPDATE/INSERT 等）")

        # 强制 LIMIT（对已包含 LIMIT 的语句不重复加）
        lower = cleaned.lower()
        if "limit" not in lower and self.db_type in ("sqlite", "mysql", "postgresql", "postgres"):
            cleaned = f"{cleaned} LIMIT {int(limit)}"

        engine = self._get_engine()
        with engine.connect() as conn:
            df = pd.read_sql_query(text(cleaned), conn)
        return df


# ============================================================
# 内部工具
# ============================================================

def _strip_sql_comments(sql: str) -> str:
    """去除 SQL 中的注释（-- 单行 和 /* */ 块）。"""
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    sql = re.sub(r"--[^\n]*", " ", sql)
    return sql
