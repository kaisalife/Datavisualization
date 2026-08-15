"""数据源接入：把请求模型转成 DataSource 并接入 DuckDB。

覆盖三类源:
1. 文件（单文件 / 多文件合并接入同一会话）
2. 数据库（PostgreSQL/MySQL/SQLite，通过 DuckDB ATTACH）
3. API（URL 拉取后注册为本地表）
"""
from __future__ import annotations

from service.runtime.exceptions import ConfigError
from service.observability import get_logger

logger = get_logger(__name__)

try:
    from service.data_ingestion import DataSource as DuckDBSource
    from service.data_ingestion import ingest as duckdb_ingest
    from service.data_ingestion import ingest_files as duckdb_ingest_files
except ImportError:
    DuckDBSource = None
    duckdb_ingest = None
    duckdb_ingest_files = None


async def ingest_data_source(model_, first_file_stem: str, agent_logs: list):
    """根据请求配置（文件/数据库/API）构建 DataSource 并接入 DuckDB。

    Args:
        model_: GenerateChartWithPromptRequest
        first_file_stem: 首个文件名 stem（单文件接入时的表名）
        agent_logs: 前端展示日志，就地追加

    Returns:
        DataProfile（含 table_name/row_count/schema/duckdb_path）

    Raises:
        ConfigError: data_ingestion 未安装 / 未提供任何源配置 / 接入失败
    """
    if duckdb_ingest is None:
        raise ConfigError("data_ingestion 模块未安装，请检查依赖")

    try:
        if model_.file_paths:
            if len(model_.file_paths) > 1:
                # 多文件: 全部接入同一个 DuckDB 会话
                profile = await duckdb_ingest_files(model_.file_paths)
            else:
                # 单文件
                source = DuckDBSource(kind="file", path=model_.file_paths[0], name=first_file_stem)
                profile = await duckdb_ingest(source)
        elif model_.db_config:
            # 数据库源
            db_type = model_.db_config.get("type", "postgresql")
            source = DuckDBSource(
                kind="database",
                db_type=db_type,
                db_config=model_.db_config,
                options={"tables": model_.db_config.get("tables"), "query": model_.db_config.get("query")},
            )
            profile = await duckdb_ingest(source)
        elif model_.api_config:
            # API 数据源
            api_cfg = model_.api_config
            source = DuckDBSource(
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
            profile = await duckdb_ingest(source)
        else:
            raise ConfigError("必须提供文件、数据库或 API 配置")
    except Exception as e:
        raise ConfigError(f"DuckDB 数据接入失败: {e}") from e

    logger.info(
        "数据接入成功",
        table=profile.table_name,
        rows=profile.row_count,
        duckdb_path=str(profile.duckdb_path),
        schema=[(c["name"], c["type"]) for c in profile.schema],
    )
    agent_logs.append(f"✅ 数据接入成功: {profile.table_name} ({profile.row_count} 行)")
    return profile
