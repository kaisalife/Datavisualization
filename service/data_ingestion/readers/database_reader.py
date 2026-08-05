"""数据库 Reader。

通过 DuckDB ATTACH 连接 PostgreSQL/MySQL/SQLite，
将指定表注册为本地视图。

两种模式:
1. 显式 SQL: 用户提供 SQL 查询 -> 创建视图
2. 表名模式: 用户指定表名 -> 注册为视图
3. 自动模式: 列出所有表 -> 用户/LLM 选择 (需要 QueryEngine 支持)
"""

from __future__ import annotations

from service.data_ingestion.duckdb_manager import DuckDBManager
from service.data_ingestion.models import DataProfile
from service.data_ingestion.profiler import build_profile, build_profiles_for_multiple_tables


class DatabaseReader:
    """从数据库读取数据，注册为 DuckDB 视图。"""

    @staticmethod
    def can_handle(db_type: str) -> bool:
        return db_type.lower() in {"postgresql", "mysql", "sqlite"}

    @staticmethod
    def _build_conn_str(db_config: dict, db_type: str) -> str:
        """构建连接字符串。"""
        if db_type == "sqlite":
            return db_config.get("database", db_config.get("path", ""))

        host = db_config.get("host", "localhost")
        port = db_config.get("port", 5432 if db_type == "postgresql" else 3306)
        database = db_config.get("database", "")
        user = db_config.get("user", db_config.get("username", ""))
        password = db_config.get("password", db_config.get("pwd", ""))

        if db_type == "postgresql":
            return f"postgresql://{user}:{password}@{host}:{port}/{database}"
        elif db_type == "mysql":
            return f"mysql://{user}:{password}@{host}:{port}/{database}"
        return ""

    @staticmethod
    def read(
        db: DuckDBManager,
        db_config: dict,
        db_type: str,
        table_name: str | None = None,
        query: str | None = None,
        tables: list[str] | None = None,
    ) -> DataProfile | list[DataProfile]:
        """连接数据库并注册表/视图。

        Args:
            db: DuckDBManager 实例
            db_config: 数据库连接配置
            db_type: "postgresql" | "mysql" | "sqlite"
            table_name: 目标表名 (可选)
            query: 自定义 SQL 查询 (优先)
            tables: 要注册的表名列表 (不传则自动发现)

        Returns:
            DataProfile (多表时返回列表)
        """
        conn_str = DatabaseReader._build_conn_str(db_config, db_type)
        alias = "source_db"
        db.attach_database(alias, conn_str, db_type)

        if query:
            # 显式 SQL 模式：在外部库上下文执行用户 SQL（裸表名），
            # 物化到本地 main schema（非 VIEW），避免 ATTACH 失效后视图不可查
            name = table_name or "query_result"
            db.register_table_from_attached_query(name, alias, query)
            return build_profile(db, name, source_kind="database", source_path=conn_str)

        # 表名模式
        target_tables = tables or DatabaseReader._list_tables(db, alias)

        if not target_tables:
            raise ValueError(f"数据库 {conn_str} 中未找到表")

        if len(target_tables) == 1:
            tbl = target_tables[0]
            name = table_name or DuckDBManager.safe_table_name(tbl)
            db.register_db_table(name, alias, tbl)
            return build_profile(db, name, source_kind="database", source_path=f"{conn_str}#{tbl}")

        # 多表模式
        table_specs = []
        for i, tbl in enumerate(target_tables):
            name = table_name if i == 0 else DuckDBManager.safe_table_name(tbl)
            if i > 0:
                name = DuckDBManager.safe_table_name(tbl)
            db.register_db_table(name, alias, tbl)
            table_specs.append((name, "database", f"{conn_str}#{tbl}"))

        profiles = build_profiles_for_multiple_tables(db, table_specs)
        return profiles

    @staticmethod
    def _list_tables(db: DuckDBManager, alias: str) -> list[str]:
        """列出 ATTACH 的数据库中的所有表。"""
        try:
            result = db.conn.sql(f"""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = '{alias}'
                OR table_name LIKE '{alias}.%'
            """).fetchall()
            tables = []
            for row in result:
                name = row[0]
                # 去掉 alias 前缀
                if name.startswith(f"{alias}."):
                    name = name[len(alias) + 1:]
                tables.append(name)
            return tables if tables else []
        except Exception:
            # 某些数据库的 information_schema 可能不同，尝试直接查询
            try:
                result = db.conn.sql(f"SHOW TABLES FROM {alias}").fetchall()
                return [row[0] for row in result]
            except Exception as e:
                print(f"[warn] _list_tables 自动发现失败 (alias={alias}): {e}")
                return []
