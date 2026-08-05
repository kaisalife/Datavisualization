"""数据接入层 -- 基于 DuckDB 的统一多源数据读取与归一化。

替代旧的 service/viz_data/ 模块。所有数据源通过 DuckDB 统一查询，
不再需要维护 8 个 Adapter + Registry + Factory + VizDataset 契约。

核心入口:
    from service.data_ingestion import ingest, DataSource

    profile = await ingest(DataSource(kind="file", path="data.csv"))
    # profile.table_name 可直接在 DuckDB SQL 中使用
"""

from service.data_ingestion.models import DataProfile, DataSource
from service.data_ingestion.router import ingest, ingest_files

__all__ = ["DataProfile", "DataSource", "ingest", "ingest_files"]
