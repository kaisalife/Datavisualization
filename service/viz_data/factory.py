"""Adapter 工厂门面：转发到 DataSourceRegistry。

保留 create_adapter API 以兼容既有调用点（service_main.py 等），
真正的路由逻辑在 registry.py 中。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

# 副作用 import：确保 adapters 子包被加载，触发装饰器注册
import service.viz_data.adapters  # noqa: F401
from service.viz_data.ports import VizDataAdapterPort
from service.viz_data.registry import DataSourceRegistry

if TYPE_CHECKING:
    from Entity import GenerateChartWithPromptRequest


def create_adapter(request: "GenerateChartWithPromptRequest") -> VizDataAdapterPort:
    """按已注册的数据源优先级派发。

    历史优先级：db_config (20) > file_paths (10)。
    未来新增源通过 @register_source 装饰器加入，无需修改本函数。

    Raises:
        AdapterError: 请求参数不匹配任何已注册数据源。
    """
    return DataSourceRegistry.resolve(request)
