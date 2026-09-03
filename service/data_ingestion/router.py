"""数据接入路由器（v4）。

统一入口: 根据数据源类型路由到对应 reader，拆分语义 series 并落盘，
返回 DataProfile（附 series_catalog）。

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

import asyncio
import time
from pathlib import Path

from service.data_ingestion.models import DataProfile, DataSource, RawTable
from service.data_ingestion.profiler import build_profile_from_df
from service.data_ingestion.readers.archive_reader import ArchiveReader
from service.data_ingestion.readers.document_reader import DocumentReader
from service.data_ingestion.readers.llm_tabular_reader import LlmTabularReader
from service.data_ingestion.readers.excel_reader import ExcelReader
from service.data_ingestion.readers.file_reader import FileReader
from service.data_ingestion.series.splitter import build_series_catalog
from service.data_ingestion.series_manager import allocate_session_dir
from service.monitoring import trace
from service.observability import get_logger

logger = get_logger(__name__)


def _assemble_profile(
    raw_tables: list[RawTable],
    session_dir: Path,
) -> DataProfile:
    """把 reader 产出的 RawTable 拆分 series、落盘，组装主 DataProfile。

    Args:
        raw_tables: reader 产出的原始表列表（>=1）
        session_dir: 当前会话目录（系列 parquet + manifest.json 落于此）

    Returns:
        主 DataProfile（series_catalog 含全部 series，related_tables 含其余表）
    """
    catalog = build_series_catalog(raw_tables, session_dir)

    # 主 profile 用第一个 raw table 的画像
    primary = raw_tables[0]
    profile = build_profile_from_df(
        primary.df, primary.name, primary.source_kind, primary.source_path
    )
    profile.session_dir = str(session_dir)
    profile.series_catalog = catalog
    # ★ 透传降级信息（任一 raw_table 降级即标记）
    for rt in raw_tables:
        if rt.degraded:
            profile.degraded = True
            profile.degraded_reason = rt.degraded_reason or profile.degraded_reason
            break

    # 其余表作为 related_tables（保持多 sheet / 多文件语义）
    if len(raw_tables) > 1:
        related = []
        for rt in raw_tables[1:]:
            p = build_profile_from_df(rt.df, rt.name, rt.source_kind, rt.source_path)
            p.session_dir = str(session_dir)
            p.series_catalog = catalog
            related.append(p)
        profile.related_tables = related

    return profile


@trace(category="ingest")
async def ingest(source: DataSource) -> DataProfile:
    """统一数据接入入口（v4，无 DuckDB）。

    分配会话目录 -> 路由 reader（返回 list[RawTable]）-> 拆分 series 落盘 -> 组装 DataProfile。
    数据以语义 series（.parquet + manifest.json）存储于会话目录。

    Args:
        source: 数据源描述

    Returns:
        DataProfile 对象（含 series_catalog）
    """
    t0 = time.perf_counter()
    session_id, session_dir = allocate_session_dir()
    t_path = time.perf_counter()

    try:
        raw_tables = await asyncio.to_thread(_route, session_dir, source)
        t_route = time.perf_counter()
        profile = await asyncio.to_thread(_assemble_profile, raw_tables, session_dir)
        t_assemble = time.perf_counter()
        logger.info(
            "ingest 完成",
            route_s=t_route - t_path,
            assemble_s=t_assemble - t_route,
            kind=source.kind,
            table=profile.table_name,
            rows=profile.row_count,
            n_series=len(profile.series_catalog.series) if profile.series_catalog else 0,
            session_id=session_id,
        )
        return profile
    except Exception:
        t_err = time.perf_counter()
        logger.error(
            "ingest ERROR",
            after_s=t_err - t0,
            kind=source.kind,
            exc_info=True,
        )
        raise


def _route(_session_dir: Path, source: DataSource) -> list[RawTable]:
    """根据数据源类型路由到对应 reader，返回 list[RawTable]。"""
    kind = source.kind

    if kind == "file":
        return _route_file(source)
    elif kind == "database":
        return _route_database(source)
    elif kind == "api":
        return _route_api(source)
    elif kind == "archive":
        return _route_archive(source)
    elif kind == "document":
        return _route_document(source)
    else:
        raise ValueError(f"未知的数据源类型: {kind}")


def _route_file(source: DataSource) -> list[RawTable]:
    """路由文件类型。根据扩展名选择 reader。"""
    path = source.path
    if not path:
        raise ValueError("file 类型数据源必须提供 path")

    # 优先级: 专用格式 > 文档格式 > 通用格式
    if FileReader.can_handle(path):
        return FileReader.read(path, table_name=source.name)
    elif ExcelReader.can_handle(path):
        return ExcelReader.read(path, table_name=source.name)
    elif LlmTabularReader.can_handle(path):
        # 文档类文本（HTML/Markdown/TXT/日志）：优先 LLM 表格化，失败回退 DocumentReader
        try:
            return LlmTabularReader.read(path, table_name=source.name)
        except Exception as e:
            logger.warning("LLM 表格化失败，回退 DocumentReader", path=path, error=str(e))
            tables = DocumentReader.read(path, table_name=source.name)
            # ★ 标记降级，让上游 plan_generator / agent_logs 看到
            reason = f"llm_tabular_failed: {e}"
            for t in tables:
                t.degraded = True
                t.degraded_reason = reason
            return tables
    elif DocumentReader.can_handle(path):
        return DocumentReader.read(path, table_name=source.name)
    elif ArchiveReader.can_handle(path):
        return ArchiveReader.read(path, table_name=source.name)
    else:
        ext = Path(path).suffix.lower()
        raise ValueError(f"不支持的文件格式: {ext}")


def _route_database(source: DataSource) -> list[RawTable]:
    """路由数据库类型。"""
    from service.data_ingestion.readers.database_reader import DatabaseReader

    if not source.db_type:
        raise ValueError("database 类型数据源必须提供 db_type")

    db_config = source.db_config or {}
    options = source.options

    return DatabaseReader.read(
        db_config=db_config,
        db_type=source.db_type,
        table_name=source.name,
        query=options.get("query"),
        tables=options.get("tables"),
    )


def _route_api(source: DataSource) -> list[RawTable]:
    """路由 API 类型。"""
    from service.data_ingestion.readers.api_reader import ApiReader

    api_params = source.api_params or {}
    options = source.options

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
        api_type=api_type,
        url=url,
        params=api_params,
        table_name=source.name,
        method=options.get("method", "GET"),
        headers=options.get("headers"),
        body=options.get("body"),
    )


def _route_archive(source: DataSource) -> list[RawTable]:
    """路由压缩包类型。"""
    if not source.path:
        raise ValueError("archive 类型数据源必须提供 path")
    return ArchiveReader.read(source.path, table_name=source.name)


def _route_document(source: DataSource) -> list[RawTable]:
    """路由文档类型 (PDF/DOCX/图片)。"""
    if not source.path:
        raise ValueError("document 类型数据源必须提供 path")
    strategy = source.options.get("strategy", "auto")
    return DocumentReader.read(source.path, table_name=source.name, strategy=strategy)


# ------------------------------------------------------------------
# 便捷函数
# ------------------------------------------------------------------

@trace(category="ingest")
async def ingest_files(paths: list[str], names: list[str] | None = None) -> DataProfile:
    """接入多个文件到同一个会话目录。

    所有文件的 series 汇总到一个会话（共享 manifest.json / 同一 datasets_dir），
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
    session_id, session_dir = allocate_session_dir()
    logger.info("ingest_files session_dir", session_id=session_id, dir=str(session_dir))

    try:
        all_raw: list[RawTable] = []
        for i, path in enumerate(paths):
            t_file_start = time.perf_counter()
            name = names[i] if names else None
            source = DataSource(kind="file", path=path, name=name)
            raws = await asyncio.to_thread(_route_file, source)
            t_file_end = time.perf_counter()
            logger.info(
                "ingest_files file",
                index=f"{i + 1}/{len(paths)}",
                name=Path(path).name,
                n_raw=len(raws),
                time_s=t_file_end - t_file_start,
            )
            all_raw.extend(raws)

        profile = await asyncio.to_thread(_assemble_profile, all_raw, session_dir)
        logger.info(
            "ingest_files assemble",
            related=len(profile.related_tables),
            n_series=len(profile.series_catalog.series) if profile.series_catalog else 0,
            total_s=time.perf_counter() - t0,
        )
        return profile
    except Exception:
        logger.error(
            "ingest_files ERROR",
            after_s=time.perf_counter() - t0,
            n_files=len(paths),
            exc_info=True,
        )
        raise


async def ingest_file(path: str, name: str | None = None) -> DataProfile:
    """便捷入口: 从文件路径自动检测类型并接入。"""
    if ArchiveReader.can_handle(path):
        kind = "archive"
    elif DocumentReader.can_handle(path):
        kind = "document"
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