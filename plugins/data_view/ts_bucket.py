"""高频时间序列分桶聚合插件（high-frequency-timeseries 技能背书）。

秒级/分钟级采样数据（传感器、监控、逐笔记录）聚合到分钟/小时桶，
再交给 Line/Bar 呈现。多个指标显式给出各自的聚合方式，不写隐性默认值。

params（全部显式传入，缺一报错）：

- ``time_column``: 时间列名（如 ``时间``）
- ``bucket``: 桶宽度，``<整数><单位>``，单位 ``s`` / ``min`` / ``H`` / ``D``
  （如 ``1min`` / ``5s`` / ``1H``）
- ``metrics``: ``{列名: 聚合方式}``，聚合方式限
  ``mean`` / ``sum`` / ``min`` / ``max`` / ``count`` / ``first`` / ``last``

输出：首列 = 桶起始时间（原始时间列名），其后每列沿用 ``metrics`` 的键名，
按桶起始时间升序；``count`` 统计桶内非空数值个数，全空桶为 0。
同一输入永远产出同一行序。
"""

VERSION = 1

import re
import pandas as pd

_AGG_ALLOWED = ("mean", "sum", "min", "max", "count", "first", "last")
_BUCKET_RE = re.compile(r"^(\d+)(s|min|H|D)$")


def apply(df, params):
    """按固定时间桶聚合多个指标，输出稳定有序。"""
    time_col = params.get("time_column")
    if not isinstance(time_col, str) or not time_col.strip():
        raise ValueError("ts_bucket 缺少必填参数 time_column")
    time_col = time_col.strip()

    bucket = params.get("bucket")
    if not isinstance(bucket, str) or not _BUCKET_RE.fullmatch(bucket.strip()):
        raise ValueError(
            f"ts_bucket 的 bucket 必须形如 1min/5s/1H/1D（得到 {bucket!r}）"
        )
    bucket = bucket.strip()

    metrics = params.get("metrics")
    if not isinstance(metrics, dict) or not metrics:
        raise ValueError("ts_bucket 缺少必填参数 metrics（{列名: 聚合方式}）")
    for col, agg in metrics.items():
        if not isinstance(col, str) or str(agg) not in _AGG_ALLOWED:
            raise ValueError(
                f"ts_bucket 的 metrics 里 {col!r}:{agg!r} 非法；聚合方式限 "
                f"{'/'.join(_AGG_ALLOWED)}"
            )
        if col.strip() == time_col:
            raise ValueError(f"ts_bucket 的指标列不能与时间列相同: {col!r}")

    missing = [time_col, *metrics.keys()]
    missing = [c for c in missing if c not in df.columns]
    if missing:
        raise ValueError(f"ts_bucket 输入缺少列: {missing}（现有: {list(df.columns)}）")

    work = df[[time_col, *metrics.keys()]].copy()
    work[time_col] = pd.to_datetime(work[time_col], errors="coerce")
    work = work.dropna(subset=[time_col])
    if work.empty:
        raise ValueError("ts_bucket 输入没有可解析的时间值")
    work = work.sort_values(time_col, kind="mergesort").reset_index(drop=True)

    bucket_col = "__bucket__"
    work[bucket_col] = work[time_col].dt.floor(bucket)

    parts = {}
    for col, agg in metrics.items():
        parts[col] = ("__num_" + col, agg)
        work["__num_" + col] = pd.to_numeric(work[col], errors="coerce")
    out = work.groupby(bucket_col, sort=True).agg(**parts).reset_index()
    labels = out.pop(bucket_col)
    out.columns = [c.removeprefix("__num_") for c in out.columns]
    out.insert(0, time_col, labels)
    return out
