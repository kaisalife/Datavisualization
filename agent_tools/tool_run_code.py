"""MCP tool: 沙箱化 run_code 服务

被 langchain_mcp_adapters 通过 stdio 协议启动为子进程。
内部委托给 agent_tools.sandbox.run_python_safely（AST 扫描 + subprocess 隔离 + 超时）。
"""

import os
import sys
import traceback

from dotenv import load_dotenv
from fastmcp import FastMCP

# 确保能导入项目根下的 agent_tools.sandbox
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_tools.sandbox import run_python_safely

load_dotenv()

mcp = FastMCP("run_code")


@mcp.tool()
def run_code(code: str) -> str:
    """
    Run the provided Python code in a sandbox and return debug information if there's an error, or "OK" if successful.

    Args:
        code: Python code to run

    Returns:
        str: "OK" if successful, or debug information if there's an error
    """
    try:
        result = run_python_safely(code, timeout=30)
    except Exception:
        return f"Exception occurred:\n{traceback.format_exc()}"

    if result.success:
        return "OK"

    parts = ["Error running code:"]
    if result.error:
        parts.append(f"Sandbox: {result.error}")
    if result.stderr:
        parts.append(f"Stderr:\n{result.stderr}")
    if result.stdout:
        parts.append(f"Stdout:\n{result.stdout}")
    parts.append(f"ReturnCode: {result.returncode}")
    return "\n".join(parts)


if __name__ == "__main__":
    mcp.run()
