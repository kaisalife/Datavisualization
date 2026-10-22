"""K 线重采样插件（financial-candlestick 技能背书）。

把分钟/日线 OHLC 行情聚合成更长周期的 K 线（周线/月线等）。
这种聚合用 SQL 写要依赖行序的 first/last，结果不可靠；插件里先按时间
稳定排序再取，保证同一输入永远产出同一结果。

params（全部显式传入，缺一报错，无隐性默认值）：

- ``time_column``: 时间列名（如 ``日期``）
- ``open`` / ``high`` / ``low`` / ``close``: 四个价格列名（输出沿用这些名字）
- ``volume``: 可选成交量列名（给出则按桶求和）
- ``freq``: 聚合周期，``D``（日）/ ``W``（周）/ ``M``（月）/ ``Q``（季）/ ``Y``（年）

输出：首列 = 时间桶标签（``2026-01-05`` / ``2026-W03`` / ``2026-01``），
列名沿用 params 里的 open/high/low/close（+volume），按时间桶升序。
"""

VERSION = 1

import pandas as pd

_FREQ_ALLOWED = ("D", "W", "M", "Q", "Y")
_BUCKET_COL = "__bucket__"


def _require(params, key):
    """取必填参数；缺失/非字符串直接报 ValueError（引擎统一转 EXEC_ERROR）。"""
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"ohlc_resample 缺少必填参数 {key}")
    return value.strip()


def apply(df, params):
    """聚合 OHLC：first/max/min/last（+volume 求和），输出稳定有序。"""
    time_col = _require(params, "time_column")
    open_col = _require(params, "open")
    high_col = _require(params, "high")
    low_col = _require(params, "low")
    close_col = _require(params, "close")
    volume_col = str(params.get("volume") or "").strip()
    freq = str(params.get("freq") or "").strip().upper()
    if freq not in _FREQ_ALLOWED:
        raise ValueError(
            f"ohlc_resample 的 freq 只支持 {'/'.join(_FREQ_ALLOWED)}（得到 {freq!r}）"
        )

    numeric_cols = [open_col, high_col, low_col, close_col] + (
        [volume_col] if volume_col else []
    )
    need = [time_col] + numeric_cols
    missing = [c for c in need if c not in df.columns]
    if missing:
        raise ValueError(f"ohlc_resample 输入缺少列: {missing}（现有: {list(df.columns)}）")

    work = df[need].copy()
    work[time_col] = pd.to_datetime(work[time_col], errors="coerce")
    for col in numeric_cols:
        work[col] = pd.to_numeric(work[col], errors="coerce")
    work = work.dropna(subset=[time_col])
    if work.empty:
        raise ValueError("ohlc_resample 输入没有可解析的时间值")

    # 稳定排序后 first/last 才有确定语义（同一输入恒同结果）
    work = work.sort_values(time_col, kind="mergesort").reset_index(drop=True)
    work[_BUCKET_COL] = pd.PeriodIndex(work[time_col], freq=freq)

    parts = {
        open_col: (open_col, "first"),
        high_col: (high_col, "max"),
        low_col: (low_col, "min"),
        close_col: (close_col, "last"),
    }
    if volume_col:
        parts[volume_col] = (volume_col, "sum")
    out = work.groupby(_BUCKET_COL, sort=True).agg(**parts).reset_index()
    labels = out.pop(_BUCKET_COL).astype(str)
    out.insert(0, time_col, labels)
    return out
