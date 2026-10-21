"""数据源表单参数解析与校验。

`/api/data-profile` 与 `/api/generate-chart-with-prompt` 共用：
把表单里的 `db_config` / `api_config` JSON 字符串解析成对象，并做早失败的合法性校验，
避免明显非法的配置进入数据接入阶段后才报错。
"""
from __future__ import annotations

import json
import re
from typing import Any

from service.data_ingestion.sql_safety import ensure_read_only

# 与 service/data_ingestion/readers/database_reader.py 支持的方言保持一致
SUPPORTED_DB_TYPES = {"postgresql", "mysql", "sqlite"}
_DB_TYPE_ALIASES = {"postgres": "postgresql"}


def parse_json_object(raw: str | None, field: str) -> dict[str, Any] | None:
    """解析表单里的 JSON 对象字段。

    Args:
        raw: 原始字符串，空 / None 视为未提供
        field: 字段名，仅用于错误信息

    Returns:
        解析后的 dict；未提供时返回 None

    Raises:
        ValueError: JSON 非法或不是对象
    """
    text = (raw or "").strip()
    if not text:
        return None
    try:
        value = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"{field} 不是合法 JSON: {e.msg}") from e
    if not isinstance(value, dict):
        raise ValueError(f"{field} 必须是 JSON 对象")
    return value


def normalize_db_type(db_config: dict[str, Any] | None) -> str | None:
    """返回归一化后的数据库类型（去空格、转小写、`postgres` -> `postgresql`）。"""
    if db_config is None:
        return None
    db_type = str(db_config.get("type") or "postgresql").strip().lower()
    return _DB_TYPE_ALIASES.get(db_type, db_type)


def normalize_db_tables(db_config: dict[str, Any] | None) -> None:
    """把 ``tables`` 统一成去空白的字符串列表。

    兼容三种来源：前端复选框/字符串（逗号、中文逗号、分号、换行分隔）、JSON 数组、
    以及历史配置里误写的其他类型（直接丢弃，交给后端读取全部表）。
    """
    if db_config is None:
        return
    tables = db_config.get("tables")
    if isinstance(tables, str):
        parts = [p.strip() for p in re.split(r"[,，;；\n]", tables) if p.strip()]
    elif isinstance(tables, (list, tuple)):
        parts = [str(p).strip() for p in tables if str(p).strip()]
    else:
        parts = []
    if parts:
        db_config["tables"] = parts
    else:
        db_config.pop("tables", None)


def validate_source_configs(
    db_config: dict[str, Any] | None, api_config: dict[str, Any] | None
) -> str | None:
    """校验数据库 / API 配置。

    Returns:
        归一化后的数据库类型；没有数据库配置时返回 None

    Raises:
        ValueError: 数据库类型不支持、sqlite 缺路径、自定义 SQL 非只读、API 缺 url/api_type
    """
    normalize_db_tables(db_config)
    if db_config is not None:
        # 自定义 SQL 只允许单条只读查询；空值直接丢掉，交给表名模式
        query = str(db_config.get("query") or "").strip()
        if query:
            ensure_read_only(query)
            db_config["query"] = query
        else:
            db_config.pop("query", None)
    db_type = normalize_db_type(db_config)
    if db_type is not None:
        if db_type not in SUPPORTED_DB_TYPES:
            raise ValueError(f"不支持的数据库类型: {db_type}")
        if db_type == "sqlite" and not (
            db_config.get("database") or db_config.get("path")
        ):
            raise ValueError("sqlite 必须提供 database/path")
    if api_config is not None and not (
        str(api_config.get("url") or "").strip() or api_config.get("api_type")
    ):
        raise ValueError("api_config 必须提供 url 或 api_type")
    return db_type
