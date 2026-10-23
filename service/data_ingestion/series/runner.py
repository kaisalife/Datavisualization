"""Series 读取执行（v4）。

load_series_df: 从 series 的 .parquet 加载 DataFrame（取代旧 run_recipe_full）。
纯 pandas 读取，无 SQL、无连接。
"""

from __future__ import annotations

import pandas as pd

from service.data_ingestion.series.models import SemanticSeries


def load_series_df(series: SemanticSeries, limit: int | None = None) -> pd.DataFrame:
    """加载一个语义 series 的 DataFrame。

    Args:
        series: 目标语义 series
        limit: 若给定，仅返回前 N 行（用于 LLM 预览）。**不会完整读取大文件**：
            优先用 pyarrow 只取第一个 batch，避免为 5 行预览把几十万行读进内存
            （parquet 是列式，但 pandas.read_parquet 仍是整表加载）。

    Returns:
        DataFrame（2-D；行标签列以真实列存在）
    """
    if limit is not None:
        try:
            import pyarrow.parquet as pq

            parquet_file = pq.ParquetFile(series.data_path)
            batch = next(parquet_file.iter_batches(batch_size=max(1, int(limit))))
            df = batch.to_pandas()
        except Exception:
            # 兼容性回退：pyarrow 不可用或文件格式异常时仍走整表读取
            df = pd.read_parquet(series.data_path).head(limit)
    else:
        df = pd.read_parquet(series.data_path)

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = ["_".join(str(x) for x in c) for c in df.columns]
    if limit is not None:
        df = df.head(limit)
    return df