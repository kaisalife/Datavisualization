"""DataFrame 语义推断工具。

主要能力：
- 从 pandas DataFrame 推断每列的 ColumnSchema（dtype + semantic_role + stats）
- 从整个 DataFrame 生成 SemanticHints（time_column、category_columns、measure_columns）
"""

from __future__ import annotations

import re
from typing import Optional

import pandas as pd

from service.viz_data.schema import ColumnSchema, SemanticHints


# 常见时间列名模式（中英文）
_TIME_NAME_PATTERNS = re.compile(
    r"(date|time|timestamp|datetime|year|month|day|quarter|季度|日期|时间|年|月|日)",
    re.IGNORECASE,
)

# 类别性列名的关键词
_CATEGORY_NAME_PATTERNS = re.compile(
    r"(type|category|region|department|group|status|class|产品|地区|部门|类型|类别|状态)",
    re.IGNORECASE,
)

# ID 列名关键词（严格匹配，避免误判）
_ID_NAME_PATTERNS = re.compile(
    r"^(id|_id|pk|primary_key|key|uuid|序号|编号)$",
    re.IGNORECASE,
)

# 度量列名关键词（数值指标）
_MEASURE_NAME_PATTERNS = re.compile(
    r"(amount|price|count|total|sum|avg|mean|value|score|rate|销售|订单|金额|数量|价格|利润|收入|成本|率|比)",
    re.IGNORECASE,
)


def infer_column_schema(series: pd.Series, name: Optional[str] = None) -> ColumnSchema:
    """从单个 Series 推断 ColumnSchema。"""
    col_name = name or str(series.name) or "unnamed"

    dtype_str = _pandas_dtype_to_str(series.dtype)
    nullable = bool(series.isna().any())
    unique_count = int(series.nunique(dropna=True))

    stats = None
    if dtype_str in ("int", "float"):
        try:
            stats = {
                "min": _safe_stat(series.min()),
                "max": _safe_stat(series.max()),
                "mean": _safe_stat(series.mean()),
            }
            # 舍弃 nan
            stats = {k: v for k, v in stats.items() if v is not None}
        except Exception:
            stats = None

    semantic_role = _infer_semantic_role(col_name, dtype_str, unique_count, len(series))

    return ColumnSchema(
        name=col_name,
        dtype=dtype_str,
        semantic_role=semantic_role,
        nullable=nullable,
        unique_count=unique_count,
        stats=stats,
    )


def dataframe_to_column_schemas(df: pd.DataFrame) -> list[ColumnSchema]:
    """整个 DataFrame → List[ColumnSchema]。"""
    return [infer_column_schema(df[c], name=str(c)) for c in df.columns]


def infer_semantic_hints(
    df: pd.DataFrame,
    columns: Optional[list[ColumnSchema]] = None,
    user_intent: Optional[str] = None,
) -> SemanticHints:
    """从 DataFrame 生成整体的 SemanticHints。"""
    if columns is None:
        columns = dataframe_to_column_schemas(df)

    time_col = None
    category_cols = []
    measure_cols = []

    for col in columns:
        if col.semantic_role == "time" and time_col is None:
            time_col = col.name
        elif col.semantic_role == "dimension":
            category_cols.append(col.name)
        elif col.semantic_role == "measure":
            measure_cols.append(col.name)

    # 生成自然分组建议
    groupings = []
    for cat in category_cols[:3]:      # 最多 3 个类别列避免爆炸
        for measure in measure_cols[:3]:
            groupings.append({"by": cat, "measure": measure})

    # 检测模式
    patterns = []
    if time_col and measure_cols:
        patterns.append("time_series")
    if category_cols and measure_cols:
        patterns.append("categorical_comparison")
    if len(measure_cols) >= 2:
        patterns.append("multi_measure")
    if not patterns:
        patterns.append("generic_tabular")

    return SemanticHints(
        time_column=time_col,
        category_columns=category_cols,
        measure_columns=measure_cols,
        natural_groupings=groupings,
        detected_patterns=patterns,
        user_intent=user_intent,
    )


# ============================================================
# 内部工具
# ============================================================

def _pandas_dtype_to_str(dtype) -> str:
    """把 pandas dtype 映射到 VizDataset 统一的 dtype 字符串。"""
    dtype_str = str(dtype).lower()
    if "int" in dtype_str:
        return "int"
    if "float" in dtype_str:
        return "float"
    if "bool" in dtype_str:
        return "bool"
    if "datetime" in dtype_str or "timedelta" in dtype_str:
        return "datetime"
    if "category" in dtype_str:
        return "category"
    return "string"


def _infer_semantic_role(
    col_name: str, dtype: str, unique_count: int, total_count: int
) -> Optional[str]:
    """根据列名 + dtype + 基数推断 semantic_role。"""
    # 时间列：dtype 是 datetime 或列名含时间关键词
    if dtype == "datetime":
        return "time"
    if _TIME_NAME_PATTERNS.search(col_name):
        return "time"

    # ID 列：列名严格匹配 ID 模式，且唯一值等于总行数
    if _ID_NAME_PATTERNS.search(col_name):
        if unique_count > 0 and total_count > 0 and unique_count == total_count:
            return "id"

    # 度量列：数值 dtype 且不是 ID
    if dtype in ("int", "float"):
        if _MEASURE_NAME_PATTERNS.search(col_name):
            return "measure"
        # 唯一值多且是数值 → measure
        if unique_count > max(10, total_count * 0.1):
            return "measure"
        return "measure"

    # 类别列：字符串/category 且基数不太高
    if dtype in ("string", "category", "bool"):
        if unique_count <= max(20, total_count * 0.3):
            return "dimension"
        return "dimension"     # 兜底

    return None


def _safe_stat(value):
    """把 numpy scalar 转成 python 原生，nan 转成 None。"""
    if value is None:
        return None
    try:
        v = value.item() if hasattr(value, "item") else value
        if isinstance(v, float) and (v != v):    # nan
            return None
        return v
    except Exception:
        return None
