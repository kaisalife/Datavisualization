"""ReadDataFileTool：带 mtime 缓存的只读数据文件读取工具。

复用 service/cache/file_read_cache.py 的 FileReadCache。
is_read_only=True，is_destructive=False，is_concurrency_safe=True。
"""

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from agent.tools.base import Decision, PermissionDecision, Tool, ToolContext, ToolOutput


class ReadDataFileInput(BaseModel):
    """ReadDataFileTool 输入。"""
    file_path: str = Field(..., description="要读取的文件路径")
    max_lines: int = Field(default=100, description="最多返回行数")


class ReadDataFileTool(Tool):
    """只读数据文件读取工具，带 mtime 缓存。"""

    def __init__(self, auto_confirm: bool = False):
        super().__init__(
            name="read_data_file",
            description="读取数据文件内容（CSV/Excel/JSON/文本），带 mtime 缓存。"
                        "返回文件内容预览。",
            args_schema=ReadDataFileInput,
            is_read_only=True,
            is_destructive=False,
            is_concurrency_safe=True,
            auto_confirm=auto_confirm,
        )

    def check_permissions(self, ctx: ToolContext) -> Decision:
        return Decision(PermissionDecision.ALLOW)

    async def call(self, input_data: Dict[str, Any], ctx: ToolContext) -> ToolOutput:
        try:
            validated = self.validate_input(input_data)
            file_path = validated.file_path
            max_lines = validated.max_lines
        except Exception as e:
            return ToolOutput(success=False, error=f"输入校验失败: {e}")

        try:
            from service.cache.file_read_cache import read_file
        except ImportError:
            try:
                from ..service.cache.file_read_cache import read_file
            except ImportError:
                import os
                if not os.path.exists(file_path):
                    return ToolOutput(success=False, error=f"文件不存在: {file_path}")
                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                lines = content.split("\n")[:max_lines]
                return ToolOutput(
                    success=True,
                    output="\n".join(lines),
                    metadata={"source": "direct_read"},
                )

        content, encoding = read_file(file_path)
        if content is None:
            return ToolOutput(success=False, error=f"文件不存在或无法读取: {file_path}")

        lines = content.split("\n")[:max_lines]
        return ToolOutput(
            success=True,
            output="\n".join(lines),
            metadata={"encoding": encoding, "total_lines": len(content.split("\n"))},
        )
