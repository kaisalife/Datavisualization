"""service 包门面：按需 re-export 公共 API。

实现分布在子包：
- pipeline/  图表生成管线（service_main 入口）
- runtime/   运行时基础设施（config / utils / query_engine ...）
- data_ingestion/  数据接入（reader + series，v4 无 DuckDB）
- monitoring/      链路追踪与错误监控
- observability/   structlog 日志
- code_completer/  代码可视化补全

**不要在包初始化时 import 重模块**：Python 导入任意子模块（如
``service.pipeline.chart_polish``）都会先执行本文件；曾经在这里急切导入
``service_main`` / ``chart_generator``，连带拉起 agent、RAG、torch、chromadb，
导致图表沙箱每次启动多花 ~30 秒（连 print 都要 32 秒）。现在用 PEP 562
惰性加载，只有真正访问门面属性时才导入对应模块。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# 保持旧行为：导入 service 任意子模块时把项目根放进 sys.path，
# 这样沙箱 / MCP 子进程里 `from agent_tools...` 也能解析（不再顺带导入重模块）。
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_LAZY_ATTRS = {
    "service_main": ("service.pipeline.service_main", "service_main"),
    "generate_single_chart": ("service.pipeline.chart_generator", "generate_single_chart"),
    "load_config": ("service.runtime.config", "load_config"),
    "get_agent_class": ("service.runtime.config", "get_agent_class"),
    "extract_json_from_response": ("service.runtime.utils", "extract_json_from_response"),
    "extract_code_from_response": ("service.runtime.utils", "extract_code_from_response"),
}

# 旧实现里这两个入口导入失败会降级为 None（其余会抛 ImportError），保持语义一致
_DEGRADABLE_ATTRS = {"service_main", "generate_single_chart"}


def __getattr__(name: str) -> Any:
    """惰性导入门面属性（PEP 562）；导入失败时与旧行为一致返回 None。"""
    if name not in _LAZY_ATTRS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    import importlib

    module_name, attr = _LAZY_ATTRS[name]
    try:
        value = getattr(importlib.import_module(module_name), attr)
    except Exception:
        if name not in _DEGRADABLE_ATTRS:
            raise
        value = None
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_ATTRS))


__all__ = [
    "service_main",
    "load_config",
    "get_agent_class",
    "extract_json_from_response",
    "extract_code_from_response",
    "generate_single_chart",
]
