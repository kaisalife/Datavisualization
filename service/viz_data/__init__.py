"""viz_data 包：多源数据适配器 + 统一 VizDataset 契约。"""

from service.viz_data.schema import (
    ArrayBlock,
    ColumnSchema,
    DataAccessor,
    DataRef,
    RawDataBundle,
    SemanticHints,
    TabularBlock,
    VizDataset,
)

# 强制加载 adapters 子包，触发 @register_source 装饰器执行。
# 若不显式导入，纯 `from service.viz_data.registry import ...` 不会触发注册。
from service.viz_data import adapters  # noqa: F401
from service.viz_data.capabilities import AdapterCapabilities
from service.viz_data.source_descriptor import SourceDescriptor

__all__ = [
    "ArrayBlock",
    "ColumnSchema",
    "DataAccessor",
    "DataRef",
    "RawDataBundle",
    "SemanticHints",
    "TabularBlock",
    "VizDataset",
    "AdapterCapabilities",
    "SourceDescriptor",
]
