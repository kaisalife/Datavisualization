"""LLM 请求头 / 环境变量解析测试（无需网络）。"""
from __future__ import annotations

import pytest

from service.runtime.utils import get_env_int, get_llm_extra_headers

pytestmark = pytest.mark.whitebox


def test_extra_headers_empty(monkeypatch):
    monkeypatch.delenv("LLM_EXTRA_HEADERS", raising=False)
    assert get_llm_extra_headers() == {}


def test_extra_headers_parses_json_object(monkeypatch):
    monkeypatch.setenv(
        "LLM_EXTRA_HEADERS",
        '{"x-opencode-session": "abc", "HTTP-Referer": "http://example.com"}',
    )
    assert get_llm_extra_headers() == {
        "x-opencode-session": "abc",
        "HTTP-Referer": "http://example.com",
    }


def test_extra_headers_invalid_json_is_ignored(monkeypatch):
    monkeypatch.setenv("LLM_EXTRA_HEADERS", "{not json")
    assert get_llm_extra_headers() == {}


def test_extra_headers_non_object_is_ignored(monkeypatch):
    monkeypatch.setenv("LLM_EXTRA_HEADERS", '["a", "b"]')
    assert get_llm_extra_headers() == {}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("42", 42), ("0", 7), ("-3", 7), ("abc", 7), ("", 7)],
)
def test_env_int_falls_back_on_invalid(monkeypatch, raw, expected):
    monkeypatch.setenv("X_TEST_INT", raw)
    assert get_env_int("X_TEST_INT", 7) == expected
