"""数据库驱动抽象：把不同 DBMS 的差异封装起来。

对 Adapter 层来说：只需要 introspect（schema 探测）+ 安全查询。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class TableIntrospection:
    """单表的元信息。"""
    name: str
    schema: Optional[str] = None            # 可选 schema/namespace（postgres/mssql）
    row_count: Optional[int] = None
    columns: list[dict] = field(default_factory=list)
    # 每项：{"name", "dtype", "nullable", "primary_key", "foreign_key"}
    sample_rows: list[list] = field(default_factory=list)  # 前 N 行


@dataclass
class DBIntrospection:
    """整库的元信息。"""
    db_type: str                            # "sqlite" | "mysql" | "postgresql" | "mssql" | ...
    database: str
    tables: list[TableIntrospection] = field(default_factory=list)

    def to_prompt_text(self, max_tables: int = 20, max_sample: int = 3) -> str:
        """LLM 友好格式：紧凑列出表名/列/样例行。"""
        lines = [f"Database: {self.db_type} / {self.database}", "Tables:"]
        for t in self.tables[:max_tables]:
            row_info = f" ({t.row_count} rows)" if t.row_count is not None else ""
            schema_prefix = f"{t.schema}." if t.schema else ""
            lines.append(f"- {schema_prefix}{t.name}{row_info}")
            for c in t.columns:
                pk = " PK" if c.get("primary_key") else ""
                fk = f" FK->{c.get('foreign_key')}" if c.get("foreign_key") else ""
                nn = " NOT NULL" if not c.get("nullable", True) else ""
                lines.append(f"    {c['name']} {c.get('dtype', '?').upper()}{pk}{fk}{nn}")
            if t.sample_rows:
                lines.append(f"  Sample rows ({min(len(t.sample_rows), max_sample)}):")
                for row in t.sample_rows[:max_sample]:
                    lines.append(f"    {row}")
        return "\n".join(lines)


class DBDriver(ABC):
    """数据库驱动抽象。"""

    @abstractmethod
    def introspect(self, tables: Optional[list[str]] = None,
                   sample_rows: int = 3) -> DBIntrospection:
        """探测数据库 schema。tables 为 None 时探测所有表。"""

    @abstractmethod
    def execute_query(self, sql: str, limit: int = 100000) -> "pd.DataFrame":
        """执行 SELECT 查询，返回 DataFrame。会强制 LIMIT 上限。"""

    @abstractmethod
    def close(self) -> None:
        """释放连接。"""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
