"""LLM API 重试机制。

参考 claude-code `services/api/withRetry.ts`：
- 指数退避 + 抖动
- 按 query_source 区分前后台：后台快速放弃
- 413 ContextOverflow 不重试（交给 reactive_compact）
- 401 Auth 不重试
- 429/5xx/timeout/connection 可重试
"""

import asyncio
import functools
from typing import Callable, Optional

from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

try:
    from openai import (
        APIConnectionError,
        APIError,
        APITimeoutError,
        AuthenticationError,
        InternalServerError,
        RateLimitError,
    )
    _OPENAI_AVAILABLE = True
except ImportError:
    _OPENAI_AVAILABLE = False


class LLMError(Exception):
    """LLM 调用基础异常。"""
    pass


class LLMRateLimitError(LLMError):
    """429 速率限制。"""
    pass


class LLMContextOverflowError(LLMError):
    """413 上下文溢出，应触发 reactive_compact。"""
    pass


class LLMAuthError(LLMError):
    """401 认证失败。"""
    pass


class LLMServerError(LLMError):
    """5xx 服务端错误。"""
    pass


class LLMTimeoutError(LLMError):
    """请求超时。"""
    pass


class LLMConnectionError(LLMError):
    """连接错误。"""
    pass


RETRYABLE_EXCEPTIONS = (
    LLMTimeoutError,
    LLMRateLimitError,
    LLMConnectionError,
    LLMServerError,
)

NON_RETRYABLE_EXCEPTIONS = (
    LLMAuthError,
    LLMContextOverflowError,
)


class QuerySource:
    """调用来源，决定重试策略。"""
    GENERATE = "generate"
    PLAN = "plan"
    PREVIEW = "preview"
    MEMORY_SELECT = "memory_select"
    AWAY_SUMMARY = "away_summary"
    COMPACT = "compact"

    BACKGROUND_SOURCES = frozenset({MEMORY_SELECT, AWAY_SUMMARY, COMPACT})

    @classmethod
    def is_background(cls, source: str) -> bool:
        return source in cls.BACKGROUND_SOURCES


def classify_error(e: Exception) -> LLMError:
    """把 openai/langchain/原生异常映射到自定义 LLM 异常。"""
    if isinstance(e, LLMError):
        return e

    if not _OPENAI_AVAILABLE:
        if isinstance(e, (TimeoutError, asyncio.TimeoutError)):
            return LLMTimeoutError(str(e))
        if isinstance(e, ConnectionError):
            return LLMConnectionError(str(e))
        return LLMError(str(e))

    if isinstance(e, AuthenticationError):
        return LLMAuthError(str(e))
    if isinstance(e, RateLimitError):
        return LLMRateLimitError(str(e))
    if isinstance(e, APITimeoutError):
        return LLMTimeoutError(str(e))
    if isinstance(e, APIConnectionError):
        return LLMConnectionError(str(e))
    if isinstance(e, InternalServerError):
        return LLMServerError(str(e))

    if isinstance(e, APIError):
        status = getattr(e, "status_code", None) or 0
        if status == 413:
            return LLMContextOverflowError(str(e))
        if status == 401:
            return LLMAuthError(str(e))
        if status == 429:
            return LLMRateLimitError(str(e))
        if 500 <= status < 600:
            return LLMServerError(str(e))

    if isinstance(e, (TimeoutError, asyncio.TimeoutError)):
        return LLMTimeoutError(str(e))
    if isinstance(e, ConnectionError):
        return LLMConnectionError(str(e))

    err_msg = str(e).lower()
    if "context length" in err_msg or "too many tokens" in err_msg or "context window" in err_msg:
        return LLMContextOverflowError(str(e))
    if "rate limit" in err_msg or "429" in err_msg:
        return LLMRateLimitError(str(e))
    if "timeout" in err_msg or "timed out" in err_msg:
        return LLMTimeoutError(str(e))
    if "connection" in err_msg:
        return LLMConnectionError(str(e))

    return LLMError(str(e))


def _get_max_attempts(query_source: str, default: int = 5) -> int:
    """后台任务只重试 1 次，前台任务重试 default 次。"""
    if QuerySource.is_background(query_source):
        return 2
    return default


def _log_retry(retry_state: RetryCallState):
    """重试时打印日志。"""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    attempt = retry_state.attempt_number
    print(f"⚠️ LLM 调用重试 {attempt}: {type(exc).__name__ if exc else 'unknown'}")


def with_retry(func: Optional[Callable] = None, *,
               query_source: str = QuerySource.GENERATE,
               max_attempts: Optional[int] = None):
    """装饰器：为 LLM 调用添加重试逻辑。

    用法：
        @with_retry(query_source="generate")
        async def my_llm_call(...): ...

        或直接装饰：
        @with_retry
        async def my_llm_call(...): ...
    """
    def decorator(fn: Callable) -> Callable:
        effective_max = max_attempts or _get_max_attempts(query_source)

        @retry(
            stop=stop_after_attempt(effective_max),
            wait=wait_exponential_jitter(initial=1, max=20),
            retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
            before_sleep=_log_retry,
            reraise=True,
        )
        @functools.wraps(fn)
        async def async_wrapper(*args, **kwargs):
            try:
                return await fn(*args, **kwargs)
            except NON_RETRYABLE_EXCEPTIONS:
                raise
            except Exception as e:
                classified = classify_error(e)
                if isinstance(classified, NON_RETRYABLE_EXCEPTIONS):
                    raise classified from e
                raise classified from e

        @retry(
            stop=stop_after_attempt(effective_max),
            wait=wait_exponential_jitter(initial=1, max=60),
            retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
            before_sleep=_log_retry,
            reraise=True,
        )
        @functools.wraps(fn)
        def sync_wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except NON_RETRYABLE_EXCEPTIONS:
                raise
            except Exception as e:
                classified = classify_error(e)
                if isinstance(classified, NON_RETRYABLE_EXCEPTIONS):
                    raise classified from e
                raise classified from e

        if asyncio.iscoroutinefunction(fn):
            return async_wrapper
        return sync_wrapper

    if func is not None and callable(func):
        return decorator(func)
    return decorator
