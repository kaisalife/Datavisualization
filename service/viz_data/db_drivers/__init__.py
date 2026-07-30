"""db_drivers 包：数据库驱动。"""

from service.viz_data.db_drivers.base import DBDriver, DBIntrospection, TableIntrospection
from service.viz_data.db_drivers.sql_driver import SqlDriver, SqlDriverError


def create_db_driver(db_config: dict) -> DBDriver:
    """根据 db_type 选择合适的驱动。"""
    db_type = str(db_config.get("db_type", "")).lower()
    sql_types = {"sqlite", "mysql", "postgresql", "postgres", "mssql", "oracle"}
    if db_type in sql_types:
        return SqlDriver(db_config)
    # 未来可加 mongo_driver
    raise SqlDriverError(f"不支持的 db_type: {db_type}")


__all__ = [
    "DBDriver",
    "DBIntrospection",
    "TableIntrospection",
    "SqlDriver",
    "SqlDriverError",
    "create_db_driver",
]
