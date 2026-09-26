"""Series 读取执行（v4）。

load_series_df: 从 series 的 .parquet 加载 DataFrame（取代旧 run_recipe_full）。
纯 pandas 读取，无 SQL、无连接。
"""

from __future__ import annotations

import pandas as pd

from service.data_ingestion.series.models import SemanticSeries


def load_series_df(series: SemanticSeries, limit: int | None = None) -> pd.DataFrame:
    """加载一个语义 series 的完整数据。

    Args:
        series: 目标语义 series
        limit: 若给定，仅返回前 N 行（用于 LLM 预览）

    Returns:
        DataFrame（2-D；行标签列以真实列存在）
    """
    df = pd.read_parquet(series.data_path)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = ["_".join(str(x) for x in c) for c in df.columns]
    if limit is not None:
        df = df.head(limit)
    return df