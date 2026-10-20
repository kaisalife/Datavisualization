"""QueryEngine token 计量测试（离线，假 chat）。"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from service.runtime.query_engine import QueryEngine

pytestmark = pytest.mark.whitebox


class _FakeChat:
    """每次调用返回固定 usage 的假模型。"""

    def __init__(self, input_tokens: int, output_tokens: int):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.calls = 0

    async def ainvoke(self, prompt):
        self.calls += 1
        return AIMessage(
            content=f"ok-{self.calls}",
            usage_metadata={
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "total_tokens": self.input_tokens + self.output_tokens,
            },
        )


async def test_usage_is_summed_and_each_call_counts():
    """两次调用各 100/20，累计必须是 200/40，而不是只有第一轮的用量。"""
    engine = QueryEngine(chat_model=_FakeChat(100, 20), model_name="gpt-4o")

    await engine.run_prompt("第一轮")
    await engine.run_prompt("第二轮")

    assert engine.usage == {"input_tokens": 200, "output_tokens": 40, "calls": 2}
    assert engine.budget_tracker.total_input_tokens == 200
    assert engine.budget_tracker.total_output_tokens == 40
    tokens = engine.cost_tracker.get_total_tokens()
    assert tokens["input_tokens"] == 200
    assert tokens["output_tokens"] == 40


async def test_dict_response_with_prompt_completion_keys():
    """BaseAgent 这类 dict 返回也要能读出 prompt/completion 命名的用量。"""

    class _DictChat:
        async def ainvoke(self, prompt):
            return {"content": "ok", "usage": {"prompt_tokens": 30, "completion_tokens": 5}}

    engine = QueryEngine(chat_model=_DictChat(), model_name="gpt-4o")
    await engine.run_prompt("hi")

    assert engine.usage["input_tokens"] == 30
    assert engine.usage["output_tokens"] == 5
