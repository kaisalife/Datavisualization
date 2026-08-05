"""数据画像生成器。

从 DuckDBManager 生成 DataProfile，供 chart_generator 消费。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from service.data_ingestion.duckdb_manager import DuckDBManager
from service.data_ingestion.models import DataProfile

# 语义角色推断的关键词
_TIME_KEYWORDS = ("date", "time", "year", "month", "day", "hour", "日期", "时间", "年", "月", "日")
_ID_KEYWORDS = ("id", "编号", "code", "uuid", "guid")
_MEASURE_KEYWORDS = ("amount", "sales", "price", "count", "sum", "total", "value", "qty", "quantity",
                     "金额", "数量", "总计", "销售额", "价格")
_NUMERIC_TYPES = ("INT", "DOUBLE", "FLOAT", "DECIMAL", "REAL", "NUMERIC", "BIGINT", "SMALLINT")
_STRING_TYPES = ("VARCHAR", "TEXT", "CHAR", "STRING")
_TIME_TYPES = ("DATE", "TIMESTAMP", "TIME", "DATETIME")


def _infer_column_semantics(
    schema: list[dict[str, str]],
    stats: dict[str, dict[str, Any]],
    row_count: int,
) -> dict[str, str]:
    """推断每列的语义角色: time / measure / dimension / id。

    Args:
        schema: [{"name":.., "type":..}, ...]
        stats: DuckDB SUMMARIZE 结果 {col: {"approx_unique":.., "type":.., ...}}
        row_count: 表行数（用于判断 id 的高唯一性）

    Returns:
        {列名: semantic_role}
    """
    semantics: dict[str, str] = {}
    for col in schema:
        name = col["name"]
        lname = name.lower()
        ctype = col["type"].upper()

        if any(k in lname for k in _TIME_KEYWORDS) or any(t in ctype for t in _TIME_TYPES):
            role = "time"
        elif any(k in lname for k in _ID_KEYWORDS):
            # id: 名字含 id 且唯一性接近行数
            approx_unique = stats.get(name, {}).get("approx_unique")
            try:
                if approx_unique and row_count > 0 and float(approx_unique) >= row_count * 0.95:
                    role = "id"
                else:
                    role = "dimension"
            except (TypeError, ValueError):
                role = "dimension"
        elif any(t in ctype for t in _NUMERIC_TYPES):
            role = "measure"
        elif any(t in ctype for t in _STRING_TYPES):
            role = "dimension"
        else:
            role = "dimension"
        semantics[name] = role
    return semantics


def _detect_patterns(column_semantics: dict[str, str]) -> list[str]:
    """根据列语义角色组合推断数据模式。

    Returns:
        ["time_series", ...] / ["categorical_comparison", ...] 等，供图表推荐。
    """
    roles = set(column_semantics.values())
    patterns: list[str] = []
    if "time" in roles and "measure" in roles:
        patterns.append("time_series")
    if "dimension" in roles and "measure" in roles:
        patterns.append("categorical_comparison")
    return patterns


def build_profile(
    db: DuckDBManager,
    table_name: str,
    source_kind: str,
    source_path: str,
    parquet_path: str | None = None,
) -> DataProfile:
    """从 DuckDB 已注册的表生成 DataProfile。

    Args:
        db: DuckDBManager 实例
        table_name: 已注册的表名
        source_kind: 数据源类型
        source_path: 原始数据源路径
        parquet_path: 标准化 parquet 路径 (如果有)

    Returns:
        DataProfile 对象
    """
    schema = db.describe(table_name)
    row_count = db.count_rows(table_name)
    preview = db.preview(table_name, limit=10)
    stats = db.summarize(table_name)

    column_semantics = _infer_column_semantics(schema, stats, row_count)
    detected_patterns = _detect_patterns(column_semantics)

    return DataProfile(
        table_name=table_name,
        source_kind=source_kind,
        source_path=source_path,
        schema=schema,
        row_count=row_count,
        preview=preview,
        stats=stats,
        duckdb_path=db.duckdb_path,
        parquet_path=parquet_path,
        column_semantics=column_semantics,
        detected_patterns=detected_patterns,
    )


def build_profiles_for_multiple_tables(
    db: DuckDBManager,
    table_specs: list[tuple[str, str, str]],  # (table_name, source_kind, source_path)
) -> list[DataProfile]:
    """为多个表生成 DataProfile 列表 (用于多 sheet Excel / 多表数据库场景)。"""
    profiles = []
    for table_name, source_kind, source_path in table_specs:
        profile = build_profile(db, table_name, source_kind, source_path)
        profiles.append(profile)

    # 第一个表的 related_tables 设为其余表
    if len(profiles) > 1:
        profiles[0].related_tables = profiles[1:]

    return profiles
