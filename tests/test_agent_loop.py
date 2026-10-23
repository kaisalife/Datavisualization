"""BaseAgent 工具循环回归：MCP 惰性加载 + 目标达成提前结束。

这些测试不联网、不启动真实 MCP 子进程，只验证 agent loop 的控制流。
"""
from __future__ import annotations

import asyncio

import pytest

import agent.basic_agent as basic_agent


class _Response:
    def __init__(self, content: str = "", tool_calls: list | None = None):
        self.content = content
        self.tool_calls = tool_calls or []


class _FakeChat:
    """最小 ChatOpenAI 替身：可绑定工具，按顺序返回预设响应。"""

    def __init__(self, responses: list[_Response] | None = None):
        self.responses = responses or [_Response("ok")]
        self.calls = 0
        self.bound_tools = None

    def bind_tools(self, tools):
        self.bound_tools = tools
        return self

    async def ainvoke(self, messages):
        index = min(self.calls, len(self.responses) - 1)
        self.calls += 1
        return self.responses[index]


class _DummyTool:
    name = "dummy"
    calls = 0

    async def ainvoke(self, args):
        type(self).calls += 1
        return "tool-ok"


@pytest.fixture(autouse=True)
def _reset_dummy_tool():
    _DummyTool.calls = 0


async def test_initialize_does_not_start_mcp(monkeypatch):
    fake_chat = _FakeChat()

    def _fake_chat_openai(**_kwargs):
        return fake_chat

    class _FailClient:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("核心路径不应在 initialize 时启动 MCP")

    monkeypatch.setattr(basic_agent, "ChatOpenAI", _fake_chat_openai)
    monkeypatch.setattr(basic_agent, "MultiServerMCPClient", _FailClient)

    agent = basic_agent.BaseAgent(
        "test-model",
        "http://localhost/v1",
        "test-key",
        {"run_code": {"command": "python", "args": ["x.py"], "transport": "stdio"}},
    )
    await agent.initialize()

    assert agent.chat is fake_chat
    assert agent.tools is None

    # 显式传 tools 时不应触发 MCP 加载
    result = await agent.arun_with_tools("hi", tools=[_DummyTool()])
    assert result["content"] == "ok"
    assert fake_chat.calls == 1


async def test_mcp_tools_are_loaded_lazily_once(monkeypatch):
    monkeypatch.setattr(basic_agent, "ChatOpenAI", lambda **_kwargs: _FakeChat())

    class _FakeMCP:
        instances = 0
        get_tools_calls = 0

        def __init__(self, *_args, **_kwargs):
            type(self).instances += 1

        async def get_tools(self):
            type(self).get_tools_calls += 1
            await asyncio.sleep(0)
            return []

    monkeypatch.setattr(basic_agent, "MultiServerMCPClient", _FakeMCP)

    agent = basic_agent.BaseAgent(
        "test-model",
        "http://localhost/v1",
        "test-key",
        {"run_code": {"command": "python", "args": ["x.py"], "transport": "stdio"}},
    )
    await agent.initialize()

    # 并发首次调用只应加载一次
    first, second = await asyncio.gather(
        agent._ensure_mcp_tools(),
        agent._ensure_mcp_tools(),
    )
    assert first == [] and second == []
    assert _FakeMCP.instances == 1
    assert _FakeMCP.get_tools_calls == 1

    # tools 为空时 arun_with_tools 降级为普通 ainvoke
    result = await agent.arun_with_tools({"user_prompt": "hi"})
    assert result["content"] == "ok"
    assert _FakeMCP.get_tools_calls == 1


async def test_should_stop_after_tool_round(monkeypatch):
    responses = [
        _Response("calling", [{"name": "dummy", "args": {}, "id": "1"}]),
        _Response("final"),
    ]
    fake_chat = _FakeChat(responses)
    monkeypatch.setattr(basic_agent, "ChatOpenAI", lambda **_kwargs: fake_chat)

    agent = basic_agent.BaseAgent("m", "http://localhost/v1", "k", {})
    await agent.initialize()

    result = await agent.arun_with_tools(
        "hi",
        tools=[_DummyTool()],
        should_stop=lambda: True,
    )

    assert result["content"] == "calling"
    assert fake_chat.calls == 1
    assert _DummyTool.calls == 1
    assert any("提前结束" in line for line in result["agent_logs"])


async def test_should_stop_false_keeps_final_round(monkeypatch):
    responses = [
        _Response("calling", [{"name": "dummy", "args": {}, "id": "1"}]),
        _Response("final"),
    ]
    fake_chat = _FakeChat(responses)
    monkeypatch.setattr(basic_agent, "ChatOpenAI", lambda **_kwargs: fake_chat)

    agent = basic_agent.BaseAgent("m", "http://localhost/v1", "k", {})
    await agent.initialize()

    result = await agent.arun_with_tools(
        "hi",
        tools=[_DummyTool()],
        should_stop=lambda: False,
    )

    assert result["content"] == "final"
    assert fake_chat.calls == 2
    assert _DummyTool.calls == 1


async def test_should_stop_exception_does_not_break_loop(monkeypatch):
    responses = [
        _Response("calling", [{"name": "dummy", "args": {}, "id": "1"}]),
        _Response("final"),
    ]
    fake_chat = _FakeChat(responses)
    monkeypatch.setattr(basic_agent, "ChatOpenAI", lambda **_kwargs: fake_chat)

    agent = basic_agent.BaseAgent("m", "http://localhost/v1", "k", {})
    await agent.initialize()

    def _boom():
        raise RuntimeError("bad predicate")

    result = await agent.arun_with_tools(
        "hi",
        tools=[_DummyTool()],
        should_stop=_boom,
    )

    assert result["content"] == "final"
    assert fake_chat.calls == 2
    assert any("判定异常" in line for line in result["agent_logs"])
