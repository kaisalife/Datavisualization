"""数据接入路由器。

统一入口: 根据数据源类型路由到对应 reader，
返回 DataProfile 供 chart_generator 消费。

使用方式:
    from service.data_ingestion import ingest, DataSource

    # 文件
    profile = await ingest(DataSource(kind="file", path="data.csv"))

    # 数据库
    profile = await ingest(DataSource(
        kind="database",
        db_type="postgresql",
        db_config={"host": "localhost", "database": "mydb", ...},
        options={"tables": ["sales", "users"]},
    ))

    # API
    profile = await ingest(DataSource(
        kind="api",
        path="worldbank",
        api_params={"indicator": "NY.GDP.MKTP.CD", "countries": "CHN;USA"},
    ))
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from service.data_ingestion.duckdb_manager import DuckDBManager, new_duckdb_path
from service.data_ingestion.models import DataProfile, DataSource
from service.data_ingestion.readers.archive_reader import ArchiveReader
from service.data_ingestion.readers.document_reader import DocumentReader
from service.data_ingestion.readers.excel_reader import ExcelReader
from service.data_ingestion.readers.file_reader import FileReader
from service.monitoring import trace
from service.observability import get_logger

logger = get_logger(__name__)


@trace(category="ingest")
async def ingest(source: DataSource) -> DataProfile:
    """统一数据接入入口。

    创建一个 DuckDBManager，路由到对应 reader，返回 DataProfile。
    数据物化到 .duckdb 文件后关闭写连接，沙箱通过 read_only 模式连接。

    Args:
        source: 数据源描述

    Returns:
        DataProfile 对象
    """
    t0 = time.perf_counter()
    session_id, duckdb_path = new_duckdb_path()
    t_path = time.perf_counter()
    db = DuckDBManager(duckdb_path)
    t_conn = time.perf_counter()

    try:
        profile = _route(db, source)
        t_route = time.perf_counter()
        logger.info(
            "ingest 完成",
            route_s=t_route - t_conn,
            path_alloc_s=t_path - t0,
            conn_s=t_conn - t_path,
            kind=source.kind,
            table=profile.table_name,
            rows=profile.row_count,
        )
        db.close()
        t_close = time.perf_counter()
        logger.info("ingest close", close_s=t_close - t_route, total_s=t_close - t0)
        return profile
    except Exception:
        db.close()
        t_err = time.perf_counter()
        logger.error(
            "ingest ERROR",
            after_s=t_err - t0,
            kind=source.kind,
            exc_info=True,
        )
        raise


def _route(db: DuckDBManager, source: DataSource) -> DataProfile:
    """根据数据源类型路由到对应 reader。"""
    kind = source.kind

    if kind == "file":
        return _route_file(db, source)
    elif kind == "database":
        return _route_database(db, source)
    elif kind == "api":
        return _route_api(db, source)
    elif kind == "archive":
        return _route_archive(db, source)
    elif kind == "document":
        return _route_document(db, source)
    else:
        raise ValueError(f"未知的数据源类型: {kind}")


def _route_file(db: DuckDBManager, source: DataSource) -> DataProfile:
    """路由文件类型。根据扩展名选择 reader。"""
    path = source.path
    if not path:
        raise ValueError("file 类型数据源必须提供 path")

    # 优先级: 专用格式 > 文档格式 > 通用格式
    if FileReader.can_handle(path):
        return FileReader.read(db, path, table_name=source.name)
    elif ExcelReader.can_handle(path):
        return ExcelReader.read(db, path, table_name=source.name)
    elif DocumentReader.can_handle(path):
        return DocumentReader.read(db, path, table_name=source.name)
    elif ArchiveReader.can_handle(path):
        return ArchiveReader.read(db, path, table_name=source.name)
    else:
        ext = Path(path).suffix.lower()
        raise ValueError(f"不支持的文件格式: {ext}")


def _route_database(db: DuckDBManager, source: DataSource) -> DataProfile:
    """路由数据库类型。"""
    from service.data_ingestion.readers.database_reader import DatabaseReader

    if not source.db_type:
        raise ValueError("database 类型数据源必须提供 db_type")

    db_config = source.db_config or {}
    options = source.options

    result = DatabaseReader.read(
        db,
        db_config=db_config,
        db_type=source.db_type,
        table_name=source.name,
        query=options.get("query"),
        tables=options.get("tables"),
    )

    if isinstance(result, list):
        return result[0]
    return result


def _route_api(db: DuckDBManager, source: DataSource) -> DataProfile:
    """路由 API 类型。"""
    from service.data_ingestion.readers.api_reader import ApiReader

    api_params = source.api_params or {}
    options = source.options

    # path 可以是内置 API 类型 (如 "worldbank") 或 URL
    api_type = None
    url = None
    if source.path:
        if source.path in ApiReader.BUILTIN_APIS:
            api_type = source.path
        else:
            url = source.path
    elif "api_type" in options:
        api_type = options["api_type"]
    elif "url" in options:
        url = options["url"]

    return ApiReader.read(
        db,
        api_type=api_type,
        url=url,
        params=api_params,
        table_name=source.name,
        method=options.get("method", "GET"),
        headers=options.get("headers"),
        body=options.get("body"),
    )


def _route_archive(db: DuckDBManager, source: DataSource) -> DataProfile:
    """路由压缩包类型。"""
    if not source.path:
        raise ValueError("archive 类型数据源必须提供 path")
    return ArchiveReader.read(db, source.path, table_name=source.name)


def _route_document(db: DuckDBManager, source: DataSource) -> DataProfile:
    """路由文档类型 (PDF/DOCX/图片)。"""
    if not source.path:
        raise ValueError("document 类型数据源必须提供 path")
    strategy = source.options.get("strategy", "auto")
    return DocumentReader.read(
        db, source.path, table_name=source.name, strategy=strategy
    )


# ------------------------------------------------------------------
# 便捷函数
# ------------------------------------------------------------------

@trace(category="ingest")
async def ingest_files(paths: list[str], names: list[str] | None = None) -> DataProfile:
    """接入多个文件到同一个 DuckDB 会话。

    所有文件注册到同一个 .duckdb 文件中，沙箱可通过同一个路径查询所有表。
    第一个文件的 DataProfile 作为主 profile，其余放入 related_tables。

    Args:
        paths: 文件路径列表
        names: 对应的表名列表 (可选，默认从文件名推导)

    Returns:
        主 DataProfile (related_tables 包含其余文件)
    """
    if not paths:
        raise ValueError("paths 不能为空")

    if len(paths) == 1:
        name = names[0] if names else None
        return await ingest(DataSource(kind="file", path=paths[0], name=name))

    t0 = time.perf_counter()
    logger.info("开始接入 N 个文件", count=len(paths))
    session_id, duckdb_path = new_duckdb_path()
    t_path = time.perf_counter()
    logger.info("ingest_files path_alloc", path_alloc_s=t_path - t0, duckdb=duckdb_path)

    db = DuckDBManager(duckdb_path)
    t_conn = time.perf_counter()
    logger.info("ingest_files conn_init", conn_init_s=t_conn - t_path)

    try:
        profiles = []
        for i, path in enumerate(paths):
            t_file_start = time.perf_counter()
            name = names[i] if names else None
            source = DataSource(kind="file", path=path, name=name)
            profile = _route_file(db, source)
            t_file_end = time.perf_counter()
            logger.info(
                "ingest_files file",
                index=f"{i + 1}/{len(paths)}",
                name=Path(path).name,
                table=profile.table_name,
                rows=profile.row_count,
                time_s=t_file_end - t_file_start,
            )
            profiles.append(profile)

        # 主 profile 设置 related_tables
        t_assemble_start = time.perf_counter()
        if len(profiles) > 1:
            profiles[0].related_tables = profiles[1:]
        t_assemble = time.perf_counter()
        logger.info(
            "ingest_files assemble",
            assemble_s=t_assemble - t_assemble_start,
            related=len(profiles) - 1,
        )

        db.close()
        t_close = time.perf_counter()
        logger.info(
            "ingest_files close",
            close_s=t_close - t_assemble,
            total_s=t_close - t0,
        )
        return profiles[0]
    except Exception:
        db.close()
        t_err = time.perf_counter()
        logger.error(
            "ingest_files ERROR",
            after_s=t_err - t0,
            n_files=len(paths),
            exc_info=True,
        )
        raise


async def ingest_file(path: str, name: str | None = None) -> DataProfile:
    """便捷入口: 从文件路径自动检测类型并接入。"""
    # 自动判断 kind
    if ArchiveReader.can_handle(path):
        kind = "archive"
    elif DocumentReader.can_handle(path):
        kind = "document"
    elif ExcelReader.can_handle(path):
        kind = "file"  # ExcelReader 通过 file 路由触发
    else:
        kind = "file"

    return await ingest(DataSource(kind=kind, path=path, name=name))


async def ingest_database(
    db_config: dict,
    db_type: str = "postgresql",
    tables: list[str] | None = None,
    query: str | None = None,
) -> DataProfile:
    """便捷入口: 从数据库接入。"""
    return await ingest(DataSource(
        kind="database",
        db_type=db_type,
        db_config=db_config,
        options={"tables": tables, "query": query},
    ))
