"""数据接入层 -- 基于 pandas + 语义 Series 的统一多源数据读取与归一化（v4）。

替代旧的 service/viz_data/ 模块，并移除了 DuckDB。
所有数据源读取为 DataFrame，拆分成面向可视化的语义 series 落盘。

核心入口:
    from service.data_ingestion import ingest, DataSource

    profile = await ingest(DataSource(kind="file", path="data.csv"))
    # profile.series_catalog.by_id("data.指标A") 取某条语义 series
"""

from service.data_ingestion.models import DataProfile, DataSource, RawTable
from service.data_ingestion.router import ingest, ingest_files
from service.data_ingestion.series.models import SemanticSeries, SeriesCatalog

__all__ = [
    "DataProfile",
    "DataSource",
    "RawTable",
    "SemanticSeries",
    "SeriesCatalog",
    "ingest",
    "ingest_files",
]