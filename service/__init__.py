"""service 包门面：只 re-export 公共 API。

实现分布在子包：
- pipeline/  图表生成管线（service_main 入口）
- runtime/   运行时基础设施（config / utils / query_engine ...）
- report/    自动报告生成（demo）
- data_ingestion/  数据接入（DuckDB）
- monitoring/      链路追踪与错误监控
- observability/   structlog 日志
- code_completer/  代码可视化补全
"""

try:
    from service.runtime.config import load_config, get_agent_class
    from service.runtime.utils import extract_json_from_response, extract_code_from_response
except ImportError:
    from .runtime.config import load_config, get_agent_class
    from .runtime.utils import extract_json_from_response, extract_code_from_response

try:
    from service.pipeline.service_main import service_main
except Exception:
    service_main = None

try:
    from service.pipeline.chart_generator import generate_single_chart
except Exception:
    generate_single_chart = None

__all__ = [
    'service_main',
    'load_config',
    'get_agent_class',
    'extract_json_from_response',
    'extract_code_from_response',
    'generate_single_chart',
]
