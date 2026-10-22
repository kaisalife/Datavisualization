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

# 日常默认只跑这些核心链路测试；其余数据接入/RAG/真实文件测试标记为 extended。
# 新增核心回归时把文件名加到这里；完整回归见 pytest.ini 注释。
CORE_TEST_FILES = {
    "test_refactor_smoke.py",
    "test_plan_contract.py",
    "test_agent_plan_fallback.py",
    "test_chart_selection.py",
    "test_chart_data_check.py",
    "test_generation_validation.py",
    "test_skill_registry.py",
    "test_industry_pareto.py",
    "test_industry_gauge.py",
    "test_industry_spc.py",
    "test_user_skills.py",
    "test_skill_injection.py",
    "test_series_shape.py",
    "test_series_split.py",
    "test_data_view_spec.py",
    "test_data_view_engine.py",
    "test_data_view_cache.py",
    "test_data_view_plugin.py",
    "test_data_view_builtin_plugins.py",
    "test_data_view_session.py",
    "test_data_view_mcp.py",
    "test_plan_view_tool.py",
    "test_chart_optimize.py",
    "test_chart_asset_inline.py",
    "test_chart_polish.py",
    "test_chart_rag.py",
}


def pytest_collection_modifyitems(config, items):
    """把核心链路之外的测试标成 extended，默认由 addopts 排除。"""
    for item in items:
        filename = Path(str(item.fspath)).name
        if filename not in CORE_TEST_FILES:
            item.add_marker(pytest.mark.extended)


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


@pytest.fixture
def client(monkeypatch, tmp_path: Path):
    """真实 Flask app + 隔离的 uploads/datasets 目录，供接口层测试使用。"""
    import app as app_module

    uploads = tmp_path / "uploads"
    uploads.mkdir()
    monkeypatch.setenv("TEMP_UPLOAD_DIR", str(uploads))
    monkeypatch.setenv("TEMP_DATASETS_DIR", str(tmp_path / "datasets"))
    old_upload = app_module.app.config["_UPLOAD_DIR"]
    app_module.app.config["_UPLOAD_DIR"] = uploads
    try:
        yield app_module.app.test_client()
    finally:
        app_module.app.config["_UPLOAD_DIR"] = old_upload
