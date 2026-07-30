"""structlog 配置 + 事件 logger。

参考 claude-code 可观测性设计：
- JSON 输出到控制台 + 文件
- 关键事件：llm_call_start、llm_call_end、tool_call、compact、memory_write、error
- 每条日志带 event + timestamp + session_id + level
"""

import logging
import sys
from pathlib import Path
from typing import Optional

import structlog


# 事件常量
EVENT_LLM_CALL_START = "llm_call_start"
EVENT_LLM_CALL_END = "llm_call_end"
EVENT_TOOL_CALL = "tool_call"
EVENT_COMPACT = "compact"
EVENT_MEMORY_WRITE = "memory_write"
EVENT_ERROR = "error"
EVENT_BUDGET_STOP = "budget_stop"
EVENT_SESSION_START = "session_start"
EVENT_SESSION_END = "session_end"


_configured = False
_log_file_path: Optional[str] = None


# 敏感字段列表：与 sanitization 模块共享
try:
    from service.observability.sanitization import redact as _redact_value
except ImportError:
    from .sanitization import redact as _redact_value


def _redact_processor(logger, method_name, event_dict):
    """structlog processor：脱敏所有事件字典中的敏感字段。"""
    return _redact_value(event_dict)


def configure_logging(
    log_path: Optional[str] = None,
    level: str = "INFO",
    json_output: bool = True,
):
    """配置 structlog，全局只需调一次。

    Args:
        log_path: 日志文件路径（None 则只输出到控制台）
        level: 日志级别（DEBUG/INFO/WARNING/ERROR）
        json_output: True 用 JSON 渲染，False 用 console 渲染
    """
    global _configured, _log_file_path

    if _configured:
        return

    log_level = getattr(logging, level.upper(), logging.INFO)

    # 标准 logging 处理器
    handlers = [logging.StreamHandler(sys.stdout)]
    if log_path:
        log_dir = Path(log_path).parent
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        handlers.append(file_handler)
        _log_file_path = log_path

    logging.basicConfig(
        level=log_level,
        handlers=handlers,
        format="%(message)s",
    )

    # structlog 配置
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        _redact_processor,   # 脱敏：所有敏感字段替换为 "***"
    ]

    if json_output:
        processors.append(structlog.processors.JSONRenderer(ensure_ascii=False))
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    _configured = True


def get_logger(name: str = "datavisual") -> structlog.BoundLogger:
    """获取一个 structlog logger。

    首次调用时自动配置（默认 INFO + JSON + 控制台）。
    """
    if not _configured:
        configure_logging()
    return structlog.get_logger(name)


def bind_session_context(session_id: str, **kwargs):
    """绑定 session 上下文到所有后续日志。"""
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(session_id=session_id, **kwargs)


def unbind_session_context():
    """清除 session 上下文。"""
    structlog.contextvars.clear_contextvars()


def get_log_file_path() -> Optional[str]:
    """返回当前日志文件路径。"""
    return _log_file_path
