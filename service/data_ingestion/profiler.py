"""数据画像生成器。

v4: 使用 pandas 直接对 DataFrame 生成 DataProfile（不再经过 DuckDB），
供 chart_generator 消费。保留下划线后缀的纯逻辑 _infer_column_semantics 与 _detect_patterns。
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd

from service.data_ingestion.models import DataProfile

# 语义角色推断的关键词
_TIME_KEYWORDS = ("date", "time", "year", "month", "day", "hour", "日期", "时间", "年", "月", "日", "季度", "周")
_ID_KEYWORDS = ("id", "编号", "code", "uuid", "guid")
_MEASURE_KEYWORDS = ("amount", "sales", "price", "count", "sum", "total", "value", "qty", "quantity",
                     "金额", "数量", "总计", "销售额", "价格")
_NUMERIC_TYPES = ("INT", "DOUBLE", "FLOAT", "DECIMAL", "REAL", "NUMERIC", "BIGINT", "SMALLINT")
_STRING_TYPES = ("VARCHAR", "TEXT", "CHAR", "STRING")
_TIME_TYPES = ("DATE", "TIMESTAMP", "TIME", "DATETIME")

# 中文时间词（按长度倒序替换，避免 "日期" 被 "日" 先拆掉）
_CN_TIME_WORDS = ("日期", "时间戳", "星期", "礼拜", "时间", "年份", "月份", "年度", "季度", "年", "月", "日", "周")
# 星期/周/礼拜 + 星期几：作为时间轴，交给自然排序
_WEEKDAY_RE = re.compile(r"^(?:星期|周|礼拜)[一二三四五六日天]$")
# 英文时间词：date/time 出现在任意位置都算；year/month 等只在末尾算
_EN_TIME_ANY = {"date", "time", "timestamp", "datetime"}
_EN_TIME_SUFFIX = {"year", "month", "day", "hour", "quarter", "week"}

_EN_ID_WORDS = {"id", "uuid", "guid", "code"}
_CN_ID_WORDS = ("编号", "代码", "编码")


def _is_id_label(name: str) -> bool:
    """判断列名是否像 id / 编号（按英文整词匹配，避免 width 命中 id）。"""
    low = str(name).lower()
    if any(word in low for word in _CN_ID_WORDS):
        return True
    tokens = [t for t in re.split(r"[^a-z]+", low) if t]
    return any(t in _EN_ID_WORDS for t in tokens)


def _is_time_label(name: str) -> bool:
    """判断列名是不是一个「时间标签」，而不是带时间词的指标名。

    这条规则用来区分两种列：
    - ``2023 年`` / ``1 月`` / ``年份`` / ``order_date`` -> 时间列；
    - ``2023 年_销售额`` / ``销售额_2023`` -> 指标列（含时间词但不是时间轴）。

    只看列名；真正的日期 dtype 由调用方另行判断。
    """
    text = str(name).strip()
    if not text:
        return False
    if _WEEKDAY_RE.fullmatch(text):
        return True
    low = text.lower()

    tokens = [t for t in re.split(r"[^a-z]+", low) if t]
    if any(t in _EN_TIME_ANY for t in tokens):
        return True
    if tokens and tokens[-1] in _EN_TIME_SUFFIX:
        return True

    # 纯年份 / 年月 / 季度
    if re.fullmatch(r"(19|20)\d{2}", low):
        return True
    if re.fullmatch(r"(19|20)\d{2}\s*[-/.年]?\s*(0?[1-9]|1[0-2])\s*月?", low):
        return True
    if re.fullmatch(r"q[1-4](\s*[-/]?\s*(19|20)\d{2})?", low):
        return True

    if not any(word in low for word in _CN_TIME_WORDS):
        return False

    # 去掉时间词、数字和分隔符后还有内容 -> 更像「指标名里带时间词」
    residual = low
    for word in sorted(_CN_TIME_WORDS, key=len, reverse=True):
        residual = residual.replace(word, "")
    residual = re.sub(r"\d+", "", residual)
    residual = re.sub(r"[\s_\-/:.()\[\]{}第号]+", "", residual)
    if not residual:
        return True
    # 「统计时间」「销售日期」这类以时间词结尾的仍算时间列
    return any(low.endswith(word) for word in _CN_TIME_WORDS)



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
        ctype = col["type"].upper()

        if any(t in ctype for t in _TIME_TYPES) or _is_time_label(name):
            role = "time"
        elif _is_id_label(name):
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


_DTYPE_TO_SEMTYPE = [
    (("datetime", "date", "time", "timestamp"), "TIMESTAMP"),
    (("int", "float", "double", "bool", "decimal", "numeric", "count"), "DOUBLE"),
]
_NUMERIC_PANDAS_KINDS = ("i", "f", "u", "b")  # int / float / uint / bool


def _dtype_to_semtype(dtype: Any) -> str:
    """把 pandas dtype 归纳为语义推断用的 canonical 类型串。

    让 _infer_column_semantics 的 _NUMERIC_TYPES/_STRING_TYPES/_TIME_TYPES
    关键词判断对 pandas dtype 依然生效。
    """
    name = str(dtype)
    low = name.lower()
    for keys, canonical in _DTYPE_TO_SEMTYPE:
        if any(k in low for k in keys):
            return canonical
    if getattr(dtype, "kind", "") in _NUMERIC_PANDAS_KINDS:
        return "DOUBLE"
    return "VARCHAR"  # object / category / 其它 -> 文本


def _df_stats(df: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """用 pandas 计算列级统计（替代 DuckDB SUMMARIZE）。"""
    stats: dict[str, dict[str, Any]] = {}
    for col in df.columns:
        s = df[col]
        col_stats: dict[str, Any] = {"type": str(s.dtype)}
        try:
            col_stats["approx_unique"] = int(s.nunique(dropna=True))
        except (TypeError, ValueError):
            pass
        try:
            if np.issubdtype(s.dtype, np.number):
                col_stats["min"] = _serialize(s.min(skipna=True))
                col_stats["max"] = _serialize(s.max(skipna=True))
                col_stats["avg"] = _serialize(s.mean(skipna=True))
                col_stats["std"] = _serialize(s.std(skipna=True))
                col_stats["q25"] = _serialize(s.quantile(0.25))
                col_stats["q50"] = _serialize(s.median(skipna=True))
                col_stats["q75"] = _serialize(s.quantile(0.75))
        except (TypeError, ValueError):
            pass
        stats[col] = col_stats
    return stats


def _json_scalar(val: Any) -> Any:
    """把单个单元格转成标准 JSON 值（NaN/Inf 一律转 null）。

    Flask 默认会把 NaN/Infinity 原样写进 JSON，``serde_json`` 等严格解析器会直接
    报错；数据预览与统计必须只输出标准 JSON。
    """
    if val is None:
        return None
    try:
        if pd.isna(val):
            return None
    except (TypeError, ValueError):
        # list/dict 等非标量会让 pd.isna 返回数组，忽略即可
        pass
    if isinstance(val, (pd.Timestamp, np.datetime64)):
        try:
            return pd.Timestamp(val).isoformat()
        except (ValueError, TypeError):
            return str(val)
    if isinstance(val, (float, np.floating)) and not np.isfinite(val):
        return None
    if hasattr(val, "item"):
        try:
            return _json_scalar(val.item())
        except (ValueError, TypeError, AttributeError):
            return str(val)
    return val


def _serialize(val: Any) -> Any:
    """把 numpy 标量 / 时间转为 JSON 可序列化值。"""
    return _json_scalar(val)


def _df_preview(df: pd.DataFrame, limit: int = 10) -> list[dict[str, Any]]:
    """前 N 行，复用旧 DuckDBManager.preview 的 JSON 序列化逻辑。"""
    records = []
    for _, row in df.head(limit).iterrows():
        records.append({col: _json_scalar(row[col]) for col in df.columns})
    return records


def build_profile_from_df(
    df: pd.DataFrame,
    table_name: str,
    source_kind: str,
    source_path: str,
) -> DataProfile:
    """从 pandas DataFrame 生成 DataProfile（v4 主路径，替代 DuckDB DESCRIBE/SUMMARIZE）。

    Args:
        df: 已读取的 DataFrame
        table_name: 逻辑表名（溯源）
        source_kind: 数据源类型
        source_path: 原始数据源路径

    Returns:
        DataProfile 对象（不含 duckdb_path；column_semantics/patterns 由纯逻辑推断）。
    """
    if df is None or df.empty:
        df = pd.DataFrame()
    schema = [{"name": str(c), "type": str(dt)} for c, dt in df.dtypes.items()]
    row_count = int(len(df))

    # 供语义推断：schema 的 type 归一化为 canonical，stats 提供 approx_unique
    sem_schema = [
        {"name": str(c), "type": _dtype_to_semtype(dtype)}
        for c, dtype in df.dtypes.items()
    ]
    stats = _df_stats(df)
    column_semantics = _infer_column_semantics(sem_schema, stats, row_count)
    detected_patterns = _detect_patterns(column_semantics)

    return DataProfile(
        table_name=table_name,
        source_kind=source_kind,
        source_path=source_path,
        schema=schema,
        row_count=row_count,
        preview=_df_preview(df),
        stats=stats,
        column_semantics=column_semantics,
        detected_patterns=detected_patterns,
    )


def build_profiles_from_dataframes(
    raw_tables: list[Any],
) -> list[DataProfile]:
    """为多个 RawTable 生成 DataProfile 列表 (多 sheet Excel / 多表数据库场景)。

    Args:
        raw_tables: list[RawTable]（含 name/df/source_kind/source_path）

    Returns:
        list[DataProfile]
    """
    profiles = []
    for rt in raw_tables:
        profile = build_profile_from_df(rt.df, rt.name, rt.source_kind, rt.source_path)
        profiles.append(profile)

    # 第一个表的 related_tables 设为其余表
    if len(profiles) > 1:
        profiles[0].related_tables = profiles[1:]

    return profiles
