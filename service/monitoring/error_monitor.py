"""错误监控器：捕获、分类、记录、推送错误事件。

在 @trace 装饰器的 except 块中自动调用，记录:
- 完整堆栈文本 + 结构化堆栈帧(含源码行)
- 局部变量摘要
- 调用链 (从 contextvar 获取)
- 错误分类 (config/parse/llm/sandbox/network/unknown)
- 出错前已执行时长
"""

import linecache
import traceback
from datetime import datetime, timezone
from uuid import uuid4

from service.observability import get_logger


class ErrorMonitor:
    """错误监控器：捕获、分类、记录、推送错误事件。"""

    _CATEGORY_MAP = {
        # config
        "ConfigError": "config",
        "KeyError": "config",
        "ValueError": "config",
        "AttributeError": "config",
        "FileNotFoundError": "config",
        "PermissionError": "config",
        "AdapterError": "config",
        # parse
        "ParserError": "parse",
        "JSONDecodeError": "parse",
        "UnicodeDecodeError": "parse",
        # llm
        "APIError": "llm",
        "TimeoutError": "llm",
        "RateLimitError": "llm",
        "AuthenticationError": "llm",
        # network
        "ConnectionError": "network",
        "WebSocketError": "network",
        "OSError": "network",
        # sandbox
        "SyntaxError": "sandbox",
        "RuntimeError": "sandbox",
        "TypeError": "sandbox",
        "IndexError": "sandbox",
        "ZeroDivisionError": "sandbox",
    }

    def __init__(self):
        self._errors: dict[str, list] = {}

    def record(
        self,
        task_id: str,
        exc: Exception,
        file_name: str = "",
        func_name: str = "",
        module: str = "",
        local_vars: dict = None,
        conversation_id: str = "",
    ) -> str:
        """记录一个错误事件，返回 error_id。

        三路分发:
        1. trace_store 内存存储
        2. structlog 持久化 (datavisual.jsonl)
        3. WebSocket 实时推送
        """
        if not task_id:
            return ""

        error_id = uuid4().hex[:12]
        error_type = type(exc).__name__
        error_category = self._classify(error_type)

        # 完整堆栈文本
        tb_text = "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        )

        # 结构化堆栈帧 (含源码行)
        frames = self._extract_frames(exc)

        # 局部变量摘要
        var_summary = self._summarize_locals(local_vars or {})

        # 调用链 (从 contextvar 获取)
        try:
            from .tracer import _call_stack
            call_chain = (_call_stack.get(None) or []).copy()
        except Exception:
            call_chain = []

        # 已执行时长
        try:
            from .trace_store import trace_store
            traces = trace_store.get_traces(task_id)
            duration_before = sum(t.get("duration_ms", 0) for t in traces)
        except Exception:
            duration_before = 0

        ts = datetime.now(timezone.utc).isoformat()

        event = {
            "error_id": error_id,
            "task_id": task_id,
            "conversation_id": conversation_id,
            "error_type": error_type,
            "error_message": str(exc),
            "error_category": error_category,
            "file_name": file_name,
            "func_name": func_name,
            "module": module,
            "traceback": tb_text,
            "traceback_frames": frames,
            "local_vars": var_summary,
            "call_chain": call_chain,
            "duration_before_error": round(duration_before, 1),
            "timestamp": ts,
        }

        # 1. 内存存储
        self._errors.setdefault(task_id, []).append(event)
        try:
            from .trace_store import trace_store
            trace_store.append_error(task_id, event)
        except Exception:
            pass

        # 2. structlog 持久化
        try:
            logger = get_logger("monitoring")
            logger.error("error_caught", **event)
        except Exception:
            pass

        # 3. WebSocket 实时推送
        try:
            from .ws_streamer import ws_streamer
            ws_streamer.broadcast(task_id, {**event, "type": "error"})
        except Exception:
            pass

        return error_id

    def _classify(self, error_type: str) -> str:
        return self._CATEGORY_MAP.get(error_type, "unknown")

    def _extract_frames(self, exc: Exception) -> list:
        """从异常 __traceback__ 提取结构化堆栈帧，含源码行。"""
        frames = []
        tb = exc.__traceback__
        while tb is not None:
            frame = tb.tb_frame
            fname = frame.f_code.co_filename.replace("\\", "/").split("/")[-1]
            lineno = tb.tb_lineno
            # 读取源码行
            code_line = ""
            try:
                code_line = linecache.getline(
                    frame.f_code.co_filename, lineno
                ).strip()
            except Exception:
                pass
            frames.append(
                {
                    "file": fname,
                    "line": lineno,
                    "func": frame.f_code.co_name,
                    "code": code_line,
                }
            )
            tb = tb.tb_next
        return frames

    def _summarize_locals(self, local_vars: dict) -> dict:
        """局部变量摘要，过滤私有变量。"""
        try:
            from .tracer import _summarize
        except Exception:
            return {}

        summary = {}
        for k, v in local_vars.items():
            if k.startswith("_"):
                continue
            summary[k] = _summarize(v)
        return summary

    def get_errors(self, task_id: str) -> list:
        return self._errors.get(task_id, [])

    def has_errors(self, task_id: str) -> bool:
        return bool(self._errors.get(task_id))

    def get_summary(self, task_id: str) -> dict:
        """任务结束时生成错误汇总。"""
        errors = self._errors.get(task_id, [])
        if not errors:
            return {"total_errors": 0}

        by_category = {}
        by_function = {}
        for e in errors:
            cat = e["error_category"]
            by_category[cat] = by_category.get(cat, 0) + 1
            fn = f'{e["file_name"]}::{e["func_name"]}'
            by_function[fn] = by_function.get(fn, 0) + 1

        return {
            "total_errors": len(errors),
            "by_category": by_category,
            "by_function": by_function,
            "first_error": errors[0]["error_id"],
            "first_error_type": errors[0]["error_type"],
            "first_error_category": errors[0]["error_category"],
            "first_error_message": errors[0]["error_message"],
        }


error_monitor = ErrorMonitor()
