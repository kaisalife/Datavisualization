"""agent 流水线本地工具池构建（从 agent_pipeline.py 拆出，v4）。"""
from __future__ import annotations

from pathlib import Path


def build_agent_tool_pool(output_folder: Path, charts_folder: Path) -> list:
    """构建 agent 本地工具池（RunCodeTool 沙箱 + 数据文件读取）。

    Args:
        output_folder: 任务输出目录（工作目录）
        charts_folder: HTML 输出目录（RunCodeTool 输出）

    Returns:
        langchain BaseTool 列表（已包装本地工具）
    """
    from agent.tools.read_data_file_tool import ReadDataFileTool
    from agent.tools.run_code_tool import RunCodeTool
    from agent.tools.base import ToolContext
    from agent.tool_adapter import wrap_local_tools
    from service.pipeline.chart_sandbox import _RENDER_HEADER

    ctx = ToolContext(auto_confirm=True, working_dir=str(output_folder))
    local_tools = [
        ReadDataFileTool(auto_confirm=True),
        RunCodeTool(
            auto_confirm=True,
            output_dir=str(charts_folder),
            prelude=_RENDER_HEADER,
        ),
    ]
    return wrap_local_tools(local_tools, ctx)