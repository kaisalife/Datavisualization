"""test_file 集成测试共享 fixtures。

本目录测试真实调用模型（读 .env），统一标记 needs_llm + integration（见
各测试文件的 pytestmark）。默认 pytest 配置（addopts 排除 needs_llm）会跳过；
显式运行需清空 addopts：
    .venv/Scripts/python.exe -m pytest tests/test_file -o addopts="" -m "needs_llm and integration"
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pytest
from dotenv import dotenv_values, load_dotenv


def _llm_env() -> tuple[str, str, str, str]:
    """读取真实模型配置：项目 .env 优先，tests/.env 的 TEST_LLM_* 兜底。"""
    load_dotenv()
    base_url = os.getenv("BASE_URL", "")
    api_key = os.getenv("API_KEY", "")
    model = os.getenv("MODEL_NAME", "")
    session = ""
    if not all((base_url, api_key, model)):
        # 根 .env 只配了一半时（例如有 BASE_URL/MODEL_NAME 但没有 API_KEY），
        # 不能逐项回退到 tests/.env，否则会把 opencode 的 key 发到 bigmodel 网关。
        test_env = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
        test_base = (test_env.get("TEST_LLM_BASE_URL") or "").strip()
        test_key = (test_env.get("TEST_LLM_API_KEY") or "").strip()
        test_model = (test_env.get("TEST_LLM_MODEL") or "").strip()
        if all((test_base, test_key, test_model)):
            base_url, api_key, model = test_base, test_key, test_model
            session = (test_env.get("TEST_LLM_SESSION") or "").strip()
    if "opencode.ai" in base_url:
        session = session or str(uuid.uuid4())
    return base_url, api_key, model, session


@pytest.fixture(scope="session")
async def real_agent():
    """真实 BaseAgent（.env 模型，mcp_config 空跳过 MCP，本地工具池可用）。"""
    base_url, api_key, model, session = _llm_env()
    if not all((base_url, api_key, model)):
        pytest.skip(".env 未配置 BASE_URL/API_KEY/MODEL_NAME")

    # opencode 网关要求 x-opencode-session；BaseAgent 通过该环境变量注入。
    # 根 .env 里可能残留占位/过期 session，这里必须覆盖，同时保留其他自定义头。
    if session:
        extra_headers = {}
        try:
            extra_headers = json.loads(os.getenv("LLM_EXTRA_HEADERS") or "{}")
            if not isinstance(extra_headers, dict):
                extra_headers = {}
        except ValueError:
            extra_headers = {}
        extra_headers["x-opencode-session"] = session
        os.environ["LLM_EXTRA_HEADERS"] = json.dumps(extra_headers)

    from agent import BaseAgent

    agent = BaseAgent(model, base_url, api_key, mcp_config={}, verbose=False)
    await agent.initialize()
    return agent

load_dotenv()


class _ChatAdapter:
    """把 langchain ChatOpenAI 包成 generate_recipes_with_llm 需要的接口。"""

    def __init__(self, llm):
        self._llm = llm

    async def ainvoke(self, msg):
        resp = await self._llm.ainvoke(msg)
        return {"content": resp.content}


@pytest.fixture(scope="session")
def real_chat():
    """真实模型 chat（.env 未配置则跳过）。"""
    base_url, api_key, model, session = _llm_env()
    if not all((base_url, api_key, model)):
        pytest.skip(".env 未配置 BASE_URL/API_KEY/MODEL_NAME")
    from langchain_openai import ChatOpenAI

    headers = {"x-opencode-session": session} if session else None
    llm = ChatOpenAI(
        base_url=base_url,
        api_key=api_key,
        model=model,
        temperature=0,
        default_headers=headers,
    )
    return _ChatAdapter(llm)


@pytest.fixture
def normal_csv(tmp_path: Path) -> Path:
    """正常多列表（中文列名，年份+地区+销售额）。"""
    path = tmp_path / "销售数据.csv"
    path.write_text(
        "年份,地区,销售额\n"
        "2025,华东,1234.5\n"
        "2025,华南,980.0\n"
        "2024,华东,1100.0\n"
        "2024,华南,870.5\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def single_col_text(tmp_path: Path) -> Path:
    """单列文本表（stats gov 式）：一列，每行引号包裹的逗号分隔文本。"""
    path = tmp_path / "年度数据单列.csv"
    path.write_text(
        "数据库：年度数据\n"
        '"2025,城镇居民人均可支配收入 (元),51231"\n'
        '"2024,城镇居民人均可支配收入 (元),49409"\n'
        '"2023,城镇居民人均可支配收入 (元),47505"\n',
        encoding="utf-8",
    )
    return path


@pytest.fixture
def wide_data() -> Path:
    """真实宽表数据（stats gov 式：指标行 × 年份列），存于本目录。"""
    path = Path(__file__).resolve().parent / "年度数据.csv"
    if not path.exists():
        pytest.skip("缺少真实数据文件 tests/test_file/年度数据.csv")
    return path
