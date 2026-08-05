"""本地 Tool -> LangChain BaseTool 适配器。

agent/tools/ 下的 Tool（abc，call + ToolContext）通过 LocalToolWrapper
包装为 LangChain BaseTool，使 BaseAgent.arun_with_tools 的 bind_tools 可用。

接入后激活了 agent/tools/ 的死代码（ReadDataFileTool/RunCodeTool），
让 agent loop 可调用本地工具而非仅 MCP 工具。
"""
from __future__ import annotations

from typing import Optional, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, PrivateAttr

from agent.tools.base import Tool, ToolContext


class LocalToolWrapper(BaseTool):
    """把本地 Tool 包装为 LangChain BaseTool。

    _arun 委托 local_tool.call(input, ctx)，返回 output.output 或错误信息。
    权限上下文 ctx 在包装时注入（自主流水线用 auto_confirm=True 直接放行）。
    """

    name: str
    description: str
    args_schema: Optional[Type[BaseModel]] = None
    _local: Tool = PrivateAttr()
    _ctx: ToolContext = PrivateAttr()

    def __init__(self, local_tool: Tool, ctx: Optional[ToolContext] = None, **kwargs):
        super().__init__(
            name=local_tool.name,
            description=local_tool.description,
            args_schema=local_tool.args_schema,
            **kwargs,
        )
        self._local = local_tool
        self._ctx = ctx or ToolContext(auto_confirm=True)

    def _run(self, **kwargs) -> str:
        import asyncio
        return asyncio.run(self._arun(**kwargs))

    async def _arun(self, **kwargs) -> str:
        try:
            output = await self._local.call(kwargs, self._ctx)
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}"
        if output.success:
            return output.output
        return f"Error: {output.error}"


def wrap_local_tools(
    tools: list[Tool], ctx: Optional[ToolContext] = None
) -> list[BaseTool]:
    """把本地 Tool 列表包装为 LangChain BaseTool 列表。"""
    return [LocalToolWrapper(t, ctx) for t in tools]
