"""@trace 装饰器 + TraceContext 上下文管理。

基于 contextvars 实现线程安全的 task_id 传递。
装饰器自动记录: 文件名、函数名、入参摘要、返回值摘要、耗时、状态、异常。
"""

import functools
import inspect
import time
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Optional

# ── 上下文变量 ──────────────────────────────────────────────

_task_id: ContextVar[str] = ContextVar("monitor_task_id", default="")
_conversation_id: ContextVar[str] = ContextVar("monitor_conv_id", default="")
_call_stack: ContextVar[list] = ContextVar("monitor_call_stack", default=None)


class TraceContext:
    """任务级追踪上下文。

    在 _run_service_main_in_executor 中使用:
        with TraceContext(task_id=task_id, conversation_id=conv_id):
            loop.run_until_complete(service_main(...))
    """

    def __init__(self, task_id: str, conversation_id: str = ""):
        self.task_id = task_id
        self.conversation_id = conversation_id
        self._tokens: list = []

    def __enter__(self):
        self._tokens.append((_task_id, _task_id.set(self.task_id)))
        self._tokens.append((_conversation_id, _conversation_id.set(self.conversation_id)))
        self._tokens.append((_call_stack, _call_stack.set([])))
        return self

    def __exit__(self, *args):
        for var, token in reversed(self._tokens):
            var.reset(token)
        self._tokens.clear()


# ── 摘要工具 ────────────────────────────────────────────────

def _summarize(obj: Any, max_len: int = 200) -> str:
    """生成对象摘要，截断到 max_len 字符。"""
    try:
        if obj is None:
            return "None"
        if isinstance(obj, str):
            return f"str({len(obj)}s)"
        if isinstance(obj, (list, tuple)):
            return f"{type(obj).__name__}({len(obj)})"
        if isinstance(obj, dict):
            return f"dict({len(obj)})"
        if hasattr(obj, "shape"):
            return f"DataFrame({obj.shape[0]}x{obj.shape[1]})"
        if isinstance(obj, (int, float, bool)):
            return str(obj)
        return type(obj).__name__
    except Exception:
        return "?"


def _summarize_args(func, args, kwargs) -> str:
    """摘要函数入参。"""
    try:
        sig = inspect.signature(func)
        params = list(sig.parameters.keys())
        parts = []
        for i, arg in enumerate(args):
            if i < len(params) and params[i] != "self":
                parts.append(f"{params[i]}={_summarize(arg)}")
            elif i < len(params):
                parts.append(f"{params[i]}={_summarize(arg)}")
            else:
                parts.append(_summarize(arg))
        for k, v in kwargs.items():
            parts.append(f"{k}={_summarize(v)}")
        return ", ".join(parts)[:200]
    except Exception:
        return "?"


# ── 事件发射 ────────────────────────────────────────────────

def _emit_trace(
    task_id: str,
    file_name: str,
    func_name: str,
    module: str,
    category: str,
    args_summary: str,
    return_summary: str,
    duration_ms: float,
    status: str,
    error_msg: str,
    ts: str,
    parent_func: str,
):
    """发送 trace 事件到三个目的地：structlog + trace_store + ws_streamer。"""
    try:
        from service.observability import get_logger
        logger = get_logger("monitoring")
        logger.info(
            "trace",
            task_id=task_id,
            file_name=file_name,
            func_name=func_name,
            module=module,
            category=category,
            args_summary=args_summary,
            return_summary=return_summary,
            duration_ms=round(duration_ms, 1),
            status=status,
            error=error_msg,
            parent_func=parent_func,
            timestamp=ts,
        )
    except Exception:
        pass

    try:
        from .trace_store import trace_store

        trace_store.append(
            task_id,
            {
                "file_name": file_name,
                "func_name": func_name,
                "module": module,
                "category": category,
                "args_summary": args_summary,
                "return_summary": return_summary,
                "duration_ms": round(duration_ms, 1),
                "status": status,
                "error": error_msg,
                "parent_func": parent_func,
                "timestamp": ts,
            },
        )
    except Exception:
        pass

    try:
        from .ws_streamer import ws_streamer

        ws_streamer.broadcast(
            task_id,
            {
                "type": "trace",
                "task_id": task_id,
                "file_name": file_name,
                "func_name": func_name,
                "category": category,
                "duration_ms": round(duration_ms, 1),
                "status": status,
                "args_summary": args_summary,
                "return_summary": return_summary,
                "error": error_msg,
                "parent_func": parent_func,
                "timestamp": ts,
            },
        )
    except Exception:
        pass


# ── 装饰器 ──────────────────────────────────────────────────

def trace(category: str = "default"):
    """函数追踪装饰器。

    自动记录:
    - file_name: 函数所在文件
    - func_name: 函数名
    - args_summary: 入参摘要
    - return_summary: 返回值摘要
    - duration_ms: 耗时(毫秒)
    - status: success / failed
    - error: 异常信息(失败时)

    用法:
        @trace(category="adapter")
        async def adapt(self, engine=None):
            ...
    """

    def decorator(func):
        is_async = inspect.iscoroutinefunction(func)
        file_name = func.__code__.co_filename.replace("\\", "/").split("/")[-1]
        module = func.__module__

        if is_async:

            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                task_id = _task_id.get("")
                func_name = func.__name__
                stack = _call_stack.get(None) or []
                parent_func = stack[-1] if stack else ""

                args_summary = _summarize_args(func, args, kwargs)
                stack_token = _call_stack.set(stack + [func_name])

                start = time.perf_counter()
                ts = datetime.now(timezone.utc).isoformat()
                status = "success"
                error_msg = ""
                return_summary = ""

                try:
                    result = await func(*args, **kwargs)
                    return_summary = _summarize(result)
                    return result
                except Exception as e:
                    status = "failed"
                    error_msg = f"{type(e).__name__}: {e}"

                    # 错误监控：捕获局部变量 + 调用 error_monitor
                    try:
                        from .error_monitor import error_monitor

                        local_vars = {}
                        tb = e.__traceback__
                        if tb and tb.tb_frame:
                            local_vars = {
                                k: v
                                for k, v in tb.tb_frame.f_locals.items()
                                if not k.startswith("_")
                            }
                        error_monitor.record(
                            task_id=task_id,
                            exc=e,
                            file_name=file_name,
                            func_name=func_name,
                            module=module,
                            local_vars=local_vars,
                            conversation_id=_conversation_id.get(""),
                        )
                    except Exception:
                        pass
                    raise
                finally:
                    duration_ms = (time.perf_counter() - start) * 1000
                    _emit_trace(
                        task_id,
                        file_name,
                        func_name,
                        module,
                        category,
                        args_summary,
                        return_summary,
                        duration_ms,
                        status,
                        error_msg,
                        ts,
                        parent_func,
                    )
                    _call_stack.reset(stack_token)

            return async_wrapper
        else:

            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                task_id = _task_id.get("")
                func_name = func.__name__
                stack = _call_stack.get(None) or []
                parent_func = stack[-1] if stack else ""

                args_summary = _summarize_args(func, args, kwargs)
                stack_token = _call_stack.set(stack + [func_name])

                start = time.perf_counter()
                ts = datetime.now(timezone.utc).isoformat()
                status = "success"
                error_msg = ""
                return_summary = ""

                try:
                    result = func(*args, **kwargs)
                    return_summary = _summarize(result)
                    return result
                except Exception as e:
                    status = "failed"
                    error_msg = f"{type(e).__name__}: {e}"

                    try:
                        from .error_monitor import error_monitor

                        local_vars = {}
                        tb = e.__traceback__
                        if tb and tb.tb_frame:
                            local_vars = {
                                k: v
                                for k, v in tb.tb_frame.f_locals.items()
                                if not k.startswith("_")
                            }
                        error_monitor.record(
                            task_id=task_id,
                            exc=e,
                            file_name=file_name,
                            func_name=func_name,
                            module=module,
                            local_vars=local_vars,
                            conversation_id=_conversation_id.get(""),
                        )
                    except Exception:
                        pass
                    raise
                finally:
                    duration_ms = (time.perf_counter() - start) * 1000
                    _emit_trace(
                        task_id,
                        file_name,
                        func_name,
                        module,
                        category,
                        args_summary,
                        return_summary,
                        duration_ms,
                        status,
                        error_msg,
                        ts,
                        parent_func,
                    )
                    _call_stack.reset(stack_token)

            return sync_wrapper

    return decorator
