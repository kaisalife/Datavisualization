"""数据源接入：把请求模型转成 DataSource 并接入（v4，无 DuckDB）。

覆盖三类源:
1. 文件（单文件 / 多文件合并接入同一会话）
2. 数据库（PostgreSQL/MySQL/SQLite，用原生客户端读入）
3. API（URL 拉取后拆分为语义 series）
"""
from __future__ import annotations

from service.runtime.exceptions import ConfigError
from service.observability import get_logger

logger = get_logger(__name__)

try:
    from service.data_ingestion import DataSource
    from service.data_ingestion import ingest
    from service.data_ingestion import ingest_files
except ImportError:
    DataSource = None
    ingest = None
    ingest_files = None


async def ingest_data_source(model_, first_file_stem: str, agent_logs: list):
    """根据请求配置（文件/数据库/API）构建 DataSource 并接入。

    Args:
        model_: GenerateChartWithPromptRequest
        first_file_stem: 首个文件名 stem（单文件接入时的表名）
        agent_logs: 前端展示日志，就地追加

    Returns:
        DataProfile（含 table_name/row_count/schema/series_catalog）

    Raises:
        ConfigError: data_ingestion 未安装 / 未提供任何源配置 / 接入失败
    """
    if ingest is None:
        raise ConfigError("data_ingestion 模块未安装，请检查依赖")

    try:
        if model_.file_paths:
            if len(model_.file_paths) > 1:
                profile = await ingest_files(model_.file_paths)
            else:
                source = DataSource(kind="file", path=model_.file_paths[0], name=first_file_stem)
                profile = await ingest(source)
        elif model_.db_config:
            db_type = model_.db_config.get("type", "postgresql")
            source = DataSource(
                kind="database",
                db_type=db_type,
                db_config=model_.db_config,
                options={"tables": model_.db_config.get("tables"), "query": model_.db_config.get("query")},
            )
            profile = await ingest(source)
        elif model_.api_config:
            api_cfg = model_.api_config
            source = DataSource(
                kind="api",
                path=api_cfg.get("url"),
                name=api_cfg.get("name"),
                api_params=api_cfg.get("params"),
                options={
                    "method": api_cfg.get("method", "GET"),
                    "headers": api_cfg.get("headers"),
                    "body": api_cfg.get("body"),
                    "api_type": api_cfg.get("api_type"),
                },
            )
            profile = await ingest(source)
        else:
            raise ConfigError("必须提供文件、数据库或 API 配置")
    except Exception as e:
        raise ConfigError(f"数据接入失败: {e}") from e

    n_series = len(profile.series_catalog.series) if profile.series_catalog else 0
    logger.info(
        "数据接入成功",
        table=profile.table_name,
        rows=profile.row_count,
        n_series=n_series,
        schema=[(c["name"], c["type"]) for c in profile.schema],
    )
    agent_logs.append(f"✅ 数据接入成功: {profile.table_name} ({profile.row_count} 行, {n_series} 个 series)")
    return profile
