"""tests 共享 fixtures。

真实模型配置放在 ``tests/.env``（被 .gitignore 忽略）。默认 addopts 会跳过
``needs_llm`` / ``needs_network`` 测试，需要显式运行：

    .venv\\Scripts\\python.exe -m pytest tests/test_table_generation_eval.py \\
        -o addopts="" -m "needs_llm and needs_network" -q -s
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from dotenv import dotenv_values

TEST_ENV_PATH = Path(__file__).with_name(".env")


def load_test_env() -> dict:
    """读取 tests/.env；文件不存在时返回空 dict。"""
    if not TEST_ENV_PATH.exists():
        return {}
    return {k: (v or "") for k, v in dotenv_values(TEST_ENV_PATH).items()}


@pytest.fixture
def test_llm_config() -> dict:
    """真实模型配置；缺失时跳过（不影响默认测试集）。"""
    cfg = load_test_env()
    api_key = cfg.get("TEST_LLM_API_KEY", "").strip()
    base_url = cfg.get("TEST_LLM_BASE_URL", "").strip()
    model = cfg.get("TEST_LLM_MODEL", "").strip()
    if not all((api_key, base_url, model)):
        pytest.skip("tests/.env 未配置 TEST_LLM_API_KEY / TEST_LLM_BASE_URL / TEST_LLM_MODEL")

    try:
        max_tokens = int(cfg.get("TEST_LLM_MAX_TOKENS") or 12000)
        timeout = int(cfg.get("TEST_LLM_TIMEOUT") or 240)
    except ValueError:
        max_tokens, timeout = 12000, 240

    return {
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
        "max_tokens": max_tokens,
        "timeout": timeout,
        # 网关要求 x-opencode-session；每次测试独立会话，避免上下文串味
        "session": cfg.get("TEST_LLM_SESSION", "").strip() or str(uuid.uuid4()),
    }


@pytest.fixture
def test_llm(test_llm_config):
    """同步 ChatOpenAI，已带上网关要求的会话头。"""
    from langchain_openai import ChatOpenAI

    headers = {}
    if "opencode.ai" in test_llm_config["base_url"]:
        headers["x-opencode-session"] = test_llm_config["session"]

    return ChatOpenAI(
        base_url=test_llm_config["base_url"],
        api_key=test_llm_config["api_key"],
        model=test_llm_config["model"],
        temperature=0,
        max_tokens=test_llm_config["max_tokens"],
        timeout=test_llm_config["timeout"],
        max_retries=1,
        default_headers=headers or None,
    )
