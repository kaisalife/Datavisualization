"""通用凭据脱敏工具。

- 供 API 响应、日志、prompt 等场景使用
- 与 observability.logger 中的 processor 保持行为一致
"""

from __future__ import annotations

from typing import Any


_SENSITIVE_KEYS = frozenset({
    "password", "passwd", "pwd", "secret",
    "api_key", "apikey", "token", "authorization",
    "access_token", "refresh_token", "private_key",
    "model_api_key",
})


def redact(value: Any) -> Any:
    """递归脱敏：dict 中命中敏感 key 的值替换为 '***'。"""
    if isinstance(value, dict):
        return {
            k: ("***" if k.lower() in _SENSITIVE_KEYS else redact(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    return value


def is_sensitive_key(key: str) -> bool:
    """判断某个 key 是否敏感。"""
    return isinstance(key, str) and key.lower() in _SENSITIVE_KEYS
