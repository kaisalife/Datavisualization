"""RunCodeTool：沙箱化 Python 代码执行工具。

封装 agent_tools/sandbox.py 的 run_python_safely，
is_destructive=True，check_permissions 需确认。
"""

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from agent.tools.base import Decision, PermissionDecision, Tool, ToolContext, ToolOutput


class RunCodeInput(BaseModel):
    """RunCodeTool 输入。"""
    code: str = Field(..., description="要执行的 Python 代码")
    timeout: int = Field(default=60, description="超时秒数")


class RunCodeTool(Tool):
    """沙箱化代码执行工具。

    is_destructive=True：代码可能修改文件系统。
    is_concurrency_safe=False：代码执行有副作用。
    """

    def __init__(self, auto_confirm: bool = False, default_cwd: Optional[str] = None):
        super().__init__(
            name="run_code",
            description="在沙箱中执行 Python 代码，返回 stdout/stderr。"
                        "禁止 os.system/subprocess/socket/eval 等危险调用。",
            args_schema=RunCodeInput,
            is_read_only=False,
            is_destructive=True,
            is_concurrency_safe=False,
            auto_confirm=auto_confirm,
        )
        self._default_cwd = default_cwd

    def check_permissions(self, ctx: ToolContext) -> Decision:
        if self._auto_confirm or ctx.auto_confirm:
            return Decision(PermissionDecision.ALLOW)
        return Decision(PermissionDecision.CONFIRM,
                        "run_code 是破坏性工具（执行代码可能修改文件），需要确认")

    async def call(self, input_data: Dict[str, Any], ctx: ToolContext) -> ToolOutput:
        try:
            validated = self.validate_input(input_data)
            code = validated.code
            timeout = validated.timeout
        except Exception as e:
            return ToolOutput(success=False, error=f"输入校验失败: {e}")

        try:
            from agent_tools.sandbox import run_python_safely
        except ImportError:
            from ..agent_tools.sandbox import run_python_safely

        cwd = ctx.working_dir or self._default_cwd
        result = run_python_safely(code, cwd=cwd, timeout=timeout)

        if result.success:
            return ToolOutput(
                success=True,
                output=result.stdout or "OK",
                metadata={"returncode": result.returncode},
            )
        else:
            error_parts = []
            if result.error:
                error_parts.append(result.error)
            if result.stderr:
                error_parts.append(f"Stderr:\n{result.stderr}")
            if result.stdout:
                error_parts.append(f"Stdout:\n{result.stdout}")
            return ToolOutput(
                success=False,
                output=result.stdout,
                error="\n".join(error_parts) or "执行失败",
                metadata={"returncode": result.returncode},
            )
