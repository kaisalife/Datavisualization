"""Tool 接口基类，参考 claude-code Tool.ts。

fail-closed 默认值：所有权限相关字段默认为最安全值。
"""

import abc
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel


class PermissionDecision(Enum):
    """权限决策。"""
    ALLOW = "allow"
    DENY = "deny"
    CONFIRM = "confirm"


@dataclass
class Decision:
    """check_permissions 返回值。"""
    decision: PermissionDecision
    message: str = ""


class ToolContext:
    """工具调用上下文。"""

    def __init__(self, session_id: str = "", user_id: str = "",
                 working_dir: str = "", auto_confirm: bool = False):
        self.session_id = session_id
        self.user_id = user_id
        self.working_dir = working_dir
        self.auto_confirm = auto_confirm


class ToolOutput:
    """工具调用结果。"""

    def __init__(self, success: bool, output: str = "", error: str = "",
                 metadata: Optional[Dict[str, Any]] = None):
        self.success = success
        self.output = output
        self.error = error
        self.metadata = metadata or {}

    def __str__(self):
        if self.success:
            return self.output
        return f"Error: {self.error}"

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "metadata": self.metadata,
        }


class Tool(abc.ABC):
    """工具抽象基类。

    fail-closed 默认值：
    - is_read_only = False（默认非只读，需显式声明）
    - is_destructive = False（但子类可覆盖）
    - is_concurrency_safe = False（默认不安全）
    - check_permissions 默认返回 CONFIRM（需确认）
    """

    def __init__(self,
                 name: str,
                 description: str,
                 args_schema: Optional[Type[BaseModel]] = None,
                 is_read_only: bool = False,
                 is_destructive: bool = False,
                 is_concurrency_safe: bool = False,
                 auto_confirm: bool = False):
        self._name = name
        self._description = description
        self._args_schema = args_schema
        self._is_read_only = is_read_only
        self._is_destructive = is_destructive
        self._is_concurrency_safe = is_concurrency_safe
        self._auto_confirm = auto_confirm

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def args_schema(self) -> Optional[Type[BaseModel]]:
        return self._args_schema

    @property
    def is_read_only(self) -> bool:
        return self._is_read_only

    @property
    def is_destructive(self) -> bool:
        return self._is_destructive

    @property
    def is_concurrency_safe(self) -> bool:
        return self._is_concurrency_safe

    def check_permissions(self, ctx: ToolContext) -> Decision:
        """权限检查。默认 fail-closed：destructive 工具需确认。"""
        if self._auto_confirm or ctx.auto_confirm:
            return Decision(PermissionDecision.ALLOW)
        if self._is_destructive:
            return Decision(PermissionDecision.CONFIRM,
                            f"工具 {self._name} 是破坏性的，需要确认")
        if self._is_read_only:
            return Decision(PermissionDecision.ALLOW)
        return Decision(PermissionDecision.CONFIRM,
                        f"工具 {self._name} 非只读，需要确认")

    def validate_input(self, input_data: Dict[str, Any]) -> Any:
        """用 args_schema 校验输入。"""
        if self._args_schema is None:
            return input_data
        return self._args_schema(**input_data)

    def render_tool_use_message(self, input_data: Dict[str, Any]) -> str:
        """渲染工具调用消息（给 LLM 看的描述）。"""
        args_str = ", ".join(f"{k}={v}" for k, v in input_data.items())
        return f"[{self._name}]({args_str})"

    @abc.abstractmethod
    async def call(self, input_data: Dict[str, Any], ctx: ToolContext) -> ToolOutput:
        """执行工具。子类必须实现。"""
        ...

    def __repr__(self):
        return (f"Tool(name={self._name}, read_only={self._is_read_only}, "
                f"destructive={self._is_destructive})")


def build_tool(tool_class: Type[Tool], **kwargs) -> Tool:
    """工具工厂，应用 fail-closed 默认值。

    确保：
    - is_read_only 默认 False
    - is_concurrency_safe 默认 False
    - check_permissions 默认 CONFIRM（除非 is_read_only 或 auto_confirm）
    """
    kwargs.setdefault("is_read_only", False)
    kwargs.setdefault("is_destructive", False)
    kwargs.setdefault("is_concurrency_safe", False)
    kwargs.setdefault("auto_confirm", False)
    return tool_class(**kwargs)


def assemble_tool_pool(tools: List[Tool]) -> List[Tool]:
    """稳定排序工具池，防止 prompt cache 失效。

    按 name 字母序排序。
    """
    return sorted(tools, key=lambda t: t.name)
