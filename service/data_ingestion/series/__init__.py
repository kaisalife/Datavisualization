"""series 包（v4）：语义化、面向可视化的数据切片。

- models:   SemanticSeries / SeriesCatalog 数据结构（含 manifest 序列化）
- splitter: 一张表 -> 多条语义 series 的确定性启发式拆分 + 落盘
- runner:   load_series_df（从 .parquet 加载）
- snippet:  series_snippet（注入仅 df 的读取片段）
- writer:   write_manifest（落盘 manifest.json）
"""
from service.data_ingestion.series.models import SemanticSeries, SeriesCatalog
from service.data_ingestion.series.runner import load_series_df
from service.data_ingestion.series.snippet import series_snippet
from service.data_ingestion.series.splitter import build_series_catalog, split_raw_table, write_manifest

__all__ = [
    "SemanticSeries",
    "SeriesCatalog",
    "build_series_catalog",
    "split_raw_table",
    "write_manifest",
    "load_series_df",
    "series_snippet",
]