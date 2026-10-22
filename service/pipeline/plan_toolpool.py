"""阶段 2 计划 agent 工具池组装（langchain 包装，v4）。"""
from __future__ import annotations


def build_plan_tool_pool(state) -> list:
    """构建阶段 2 agent 工具池（7 个工具）。

    Args:
        state: PlanSessionState（共享 series 目录/画像/日志/plans）

    Returns:
        langchain BaseTool 列表
    """
    from agent.tools.base import ToolContext
    from agent.tool_adapter import wrap_local_tools
    from service.pipeline.plan_create_tool import CreatePlanTool, PreviewSeriesTool
    from service.pipeline.plan_recipe_tools import (
        GetSeriesTool,
        ListSeriesTool,
        LoadSkillTool,
    )
    from service.pipeline.plan_view_tool import DescribeDatasetTool, RunViewTool

    ctx = ToolContext(auto_confirm=True)
    datasets_dir = getattr(state.catalog, "datasets_dir", "") if state.catalog else ""
    local_tools = [
        ListSeriesTool(state.catalog),
        GetSeriesTool(state.catalog),
        PreviewSeriesTool(state.catalog),
        DescribeDatasetTool(datasets_dir),
        RunViewTool(state),
        LoadSkillTool(),
        CreatePlanTool(state),
    ]
    return wrap_local_tools(local_tools, ctx)