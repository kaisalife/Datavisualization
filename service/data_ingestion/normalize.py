"""数值列归一化：把「长得像数字的文本」转成真正的数值。

视觉模型抽表、Excel/CSV 报表里常见 ``1,200``、``12.5%``、``(1,200)`` 这类文本。
如果保持 object，profiler 会把它们当维度，series 拆分和图表都会退化。

转换是保守的：
- 只有整列**所有**非空值都能解析时才转，任何一个值失败就整列保留原样；
- 列名像编号 / 电话 / 身份证的列不转；
- 带单位（``1,200 万元``）不转，避免丢失量纲；
- 前导零（``00123``）、超长数字（电话/身份证）保持字符串。

入口：``coerce_numeric_columns(df)``，由 ``router._assemble_profile`` 在
profiling / series 拆分之前统一调用。
"""
from __future__ import annotations

import math
import re
import unicodedata
from numbers import Number

import pandas as pd

# 解析失败的哨兵（与 None / NaN 区分）
_FAIL = object()

_NULL_TOKENS = {
    "",
    "-",
    "--",
    "—",
    "–",
    "−",
    "n/a",
    "na",
    "null",
    "none",
    "nan",
    "无",
    "暂无",
    "未知",
    "不适用",
}

_CURRENCY_SYMBOLS = "¥￥$€£"
_NUMBER_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")
# 抽样快速判断：值里是否可能存在数字（避免对纯文本列做全表逐格解析）
_NUMBER_HINT_RE = re.compile(r"^[\s(（]?[¥￥$€£]?\s*[+-]?\d")

_IDENTIFIER_CN = ("编号", "代码", "编码", "邮编", "电话", "手机", "身份证", "账号", "账户")
_IDENTIFIER_EN = {"id", "uuid", "guid", "code", "zip", "phone", "tel", "account"}


def _clean_text(value: str) -> str:
    """全角转半角、去首尾空白。"""
    return unicodedata.normalize("NFKC", value).strip()


def _looks_like_identifier(column) -> bool:
    """列名是否像编号类字段（这类列即使全是数字也不该转数值）。"""
    low = str(column).lower()
    if any(word in low for word in _IDENTIFIER_CN):
        return True
    tokens = [t for t in re.split(r"[^a-z]+", low) if t]
    return any(t in _IDENTIFIER_EN for t in tokens)


def _parse_number(value):
    """尝试把一个单元格解析成 int / float / NaN。

    Returns:
        数值、NaN（空值/占位符），或 ``_FAIL``（不是数值文本）。
    """
    if isinstance(value, bool):
        return _FAIL
    if isinstance(value, Number):
        if isinstance(value, float) and math.isnan(value):
            return math.nan
        return value
    if value is None:
        return math.nan
    if not isinstance(value, str):
        return _FAIL

    text = _clean_text(value)
    if text.lower() in _NULL_TOKENS:
        return math.nan

    # 会计负数：(1,200) -> -1200
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1].strip()

    text = text.replace("−", "-")
    while text and text[0] in _CURRENCY_SYMBOLS:
        text = text[1:].strip()

    # 百分数保留百分点：12.5% -> 12.5（不除以 100）
    if text.endswith("%"):
        text = text[:-1].strip()

    # 千分位；同时兼容 "1.234,56" 这种欧式写法
    if "," in text and "." in text and text.rfind(",") > text.rfind("."):
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(",", "")
    text = (
        text.replace(" ", "")
        .replace("\u00a0", "")
        .replace("\u2009", "")
        .replace("\u202f", "")
    )

    if not _NUMBER_RE.fullmatch(text):
        return _FAIL

    integer_part = text.lstrip("+-").split(".", 1)[0]
    # 00123 这类编码保留字符串
    if len(integer_part) > 1 and integer_part.startswith("0"):
        return _FAIL
    # 无分隔符的长数字更可能是电话/身份证/长编码
    if "." not in text and len(integer_part) >= 12:
        return _FAIL

    number = float(text)
    if negative:
        number = -number
    return int(number) if number.is_integer() else number


def _looks_numeric(value) -> bool:
    """快速判断值是否可能以数字开头（用于跳过纯文本列）。"""
    if isinstance(value, bool):
        return False
    if isinstance(value, Number):
        return True
    if not isinstance(value, str):
        return False
    return bool(_NUMBER_HINT_RE.match(unicodedata.normalize("NFKC", value)))


def coerce_numeric_columns(df: pd.DataFrame) -> pd.DataFrame:
    """把整列都是数字文本的列转成数值；不满足条件时原样返回。

    Args:
        df: 原始 DataFrame（不会原地修改）

    Returns:
        转换后的新 DataFrame（列顺序不变）
    """
    if df is None or df.empty:
        return df

    result = df.copy()
    for col in result.columns:
        series = result[col]
        if pd.api.types.is_numeric_dtype(series) or pd.api.types.is_datetime64_any_dtype(series):
            continue
        if _looks_like_identifier(col):
            continue

        non_null = series.dropna()
        if non_null.empty:
            continue
        # 前 50 个值里都没有数字迹象，直接跳过，避免全表扫描
        if not any(_looks_numeric(v) for v in non_null.head(50)):
            continue

        converted: list = []
        numeric_count = 0
        for value in series.tolist():
            parsed = _parse_number(value)
            if parsed is _FAIL:
                converted = []
                break
            converted.append(parsed)
            if not (isinstance(parsed, float) and math.isnan(parsed)):
                numeric_count += 1

        if not converted or numeric_count == 0:
            continue
        result[col] = pd.Series(converted, index=result.index)

    return result
