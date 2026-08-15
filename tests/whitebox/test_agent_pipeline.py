"""agent_pipeline + LocalToolWrapper 单元测试。

注:项目存在 agent/__init__ <-> service/__init__ 循环导入(既有问题,非本测试引入)。
用 module 级 autouse fixture 在 setup 时 mock service.monitoring 阻断循环,
teardown 恢复 sys.modules,避免污染其他测试(黑盒 app fixture)。
agent import 延迟到测试函数内(在 fixture mock 生效后)。
"""
import asyncio
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True, scope="module")
def _mock_service_monitoring():
    """mock service.monitoring 阻断循环导入,teardown 恢复 sys.modules。"""
    orig = {k: sys.modules.get(k) for k in ["service", "service.monitoring"]}
    if "service.monitoring" not in sys.modules:
        _svc = types.ModuleType("service")
        _svc.__path__ = [str(_ROOT / "service")]
        sys.modules["service"] = _svc
        _mon = types.ModuleType("service.monitoring")
        _mon.trace = lambda *a, **k: (lambda fn: fn)
        sys.modules["service.monitoring"] = _mon
    yield
    # teardown: 恢复原始状态,避免污染其他测试模块
    for k, v in orig.items():
        if v is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = v


# ===== LocalToolWrapper =====

class TestLocalToolWrapper:
    def test_wraps_name_and_delegates(self):
        from agent.tool_adapter import LocalToolWrapper
        from agent.tools.base import Tool, ToolContext, ToolOutput

        local = MagicMock(spec=Tool)
        local.name = "mock_tool"
        local.description = "a mock tool"
        local.args_schema = None
        local.call = AsyncMock(return_value=ToolOutput(success=True, output="result42"))

        wrapped = LocalToolWrapper(local, ToolContext(auto_confirm=True))
        assert wrapped.name == "mock_tool"
        assert wrapped.description == "a mock tool"
        out = asyncio.run(wrapped._arun(x=1))
        assert out == "result42"
        local.call.assert_awaited_once()

    def test_error_returned_as_string(self):
        from agent.tool_adapter import LocalToolWrapper
        from agent.tools.base import Tool, ToolOutput

        local = MagicMock(spec=Tool)
        local.name = "fail_tool"
        local.description = "fails"
        local.args_schema = None
        local.call = AsyncMock(return_value=ToolOutput(success=False, error="boom"))

        wrapped = LocalToolWrapper(local)
        out = asyncio.run(wrapped._arun(x=1))
        assert "boom" in out

    def test_wrap_local_tools_list(self):
        from agent.tool_adapter import wrap_local_tools
        from agent.tools.base import Tool, ToolOutput

        local = MagicMock(spec=Tool)
        local.name = "t1"
        local.description = "d"
        local.args_schema = None
        local.call = AsyncMock(return_value=ToolOutput(success=True, output="ok"))

        tools = wrap_local_tools([local])
        assert len(tools) == 1
        assert tools[0].name == "t1"


# ===== run_agent_pipeline =====

def _make_chat(fake_arun, plan_content=None):
    chat = MagicMock()
    chat.arun_with_tools = fake_arun
    # plan 阶段 ainvoke mock
    if plan_content is None:
        plan_content = '{"plans":[{"plan_id":"1","plan_name":"p1","chart_type":"Bar","chart_title":"t","x_axis":"a","y_axis":["b"],"use_column_names":true,"execution_order":1,"data_interface":{"available":false}}]}'

    async def fake_ainvoke(prompt):
        return {"content": plan_content, "agent_logs": []}
    chat.ainvoke = fake_ainvoke
    return chat


def _make_model(viz_mode="agent", file_paths=None):
    model_ = MagicMock()
    model_.file_paths = file_paths if file_paths is not None else ["a.csv"]
    model_.user_prompt = "画图"
    model_.viz_mode = viz_mode
    model_.config = None
    model_.mcp_prompt = ""
    model_.skill_prompt = ""
    return model_


def _make_profile():
    profile = MagicMock()
    profile.duckdb_path = "/tmp/x.duckdb"
    profile.table_name = "t"
    profile.to_prompt_dict.return_value = {"schema": []}
    profile.to_prompt_str.return_value = "数据预览"
    return profile


class TestRunAgentPipeline:
    async def test_collects_new_charts_only(self, tmp_path):
        from service.pipeline.agent_pipeline import run_agent_pipeline

        output_folder = tmp_path / "out"
        charts = output_folder / "charts"
        charts.mkdir(parents=True)
        (charts / "old.html").write_text("old")  # 预存文件,不应计入

        async def fake_arun(prompt, max_iterations=18, tools=None, config=None):
            (charts / "chart_new1.html").write_text("new")
            return {"content": "done", "agent_logs": ["llm done"], "tool_calls": [{"name": "run_code"}]}

        result = await run_agent_pipeline(
            _make_chat(fake_arun), _make_model(), _make_profile(), output_folder, task_id=None
        )

        assert len(result["successful_charts"]) == 1
        assert result["successful_charts"][0]["plan"]["plan_name"] == "chart_new1.html"
        assert result["successful_charts"][0]["chart_path"].endswith("chart_new1.html")
        names = [c["plan"]["plan_name"] for c in result["successful_charts"]]
        assert "old.html" not in names
        assert "successful_charts" in result
        assert "failed_plans" in result
        assert "agent_logs" in result
        assert len(result["failed_plans"]) == 0

    async def test_no_charts_produced(self, tmp_path):
        from service.pipeline.agent_pipeline import run_agent_pipeline

        output_folder = tmp_path / "out"

        async def fake_arun(prompt, max_iterations=18, tools=None, config=None):
            return {"content": "done", "agent_logs": [], "tool_calls": []}

        result = await run_agent_pipeline(
            _make_chat(fake_arun), _make_model(), _make_profile(), output_folder, task_id=None
        )

        assert len(result["successful_charts"]) == 0
        assert len(result["failed_plans"]) == 1
        assert "未产出图表" in result["failed_plans"][0]["error"]

    async def test_agent_exception_handled(self, tmp_path):
        from service.pipeline.agent_pipeline import run_agent_pipeline

        output_folder = tmp_path / "out"

        async def fake_arun(prompt, max_iterations=18, tools=None, config=None):
            raise RuntimeError("LLM down")

        result = await run_agent_pipeline(
            _make_chat(fake_arun), _make_model(), _make_profile(), output_folder, task_id=None
        )

        assert len(result["successful_charts"]) == 0
        assert len(result["failed_plans"]) == 1
        assert "LLM down" in result["failed_plans"][0]["error"]

    async def test_plan_stage_produces_blueprint(self, tmp_path):
        from service.pipeline.agent_pipeline import run_agent_pipeline
        output_folder = tmp_path / "out"
        captured_prompt = []

        async def fake_arun(prompt, max_iterations=18, tools=None, config=None):
            captured_prompt.append(str(prompt))
            return {"content": "done", "agent_logs": [], "tool_calls": []}

        plan_content = '{"plans":[{"plan_id":"1","plan_name":"销售趋势","chart_type":"Line","chart_title":"t","x_axis":"month","y_axis":["sales"],"use_column_names":true,"execution_order":1,"data_interface":{"available":false}}]}'
        result = await run_agent_pipeline(
            _make_chat(fake_arun, plan_content=plan_content),
            _make_model(), _make_profile(), output_folder, task_id=None
        )

        # plan 阶段产出规划
        assert any("plan 层规划" in l for l in result["agent_logs"])
        # all_plans.json 保存
        assert (output_folder / "all_plans.json").exists()
        # planned_charts 注入自主 prompt
        assert "销售趋势" in captured_prompt[0]
