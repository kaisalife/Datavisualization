"""阶段 2 计划 agent 工具：试查与提交 plan（v4）。

- preview_series: 只读采样某条语义 series（确认数据可行）
- create_plan:    提交一个 plan（即时确定性校验，通过/降级/丢弃当场反馈给 agent）
"""
from __future__ import annotations

from typing import Any, Dict

from pydantic import BaseModel, Field

from agent.tools.base import Decision, PermissionDecision, Tool, ToolContext, ToolOutput
from agent.tools.read_table_sample_tool import ReadSeriesSampleTool
from service.pipeline.plan_state import PlanSessionState
from service.pipeline.plan_validator import validate_one_plan


class PreviewSeriesTool(ReadSeriesSampleTool):
    """只读采样 series（规划期验证数据/变换可行性）。"""

    def __init__(self, catalog, auto_confirm: bool = True):
        super().__init__(catalog=catalog, auto_confirm=auto_confirm)
        self._name = "preview_series"
        self._description = (
            "只读查看某个语义 series 的真实数据（自动限行）。规划时验证该 series 是否适用于"
            "某个图表/变换（如确认行标签、列标签、取值）。"
        )


class CreatePlanInput(BaseModel):
    """create_plan 输入。"""

    plan: dict = Field(..., description="一个 plan 的完整 JSON（见系统提示的 plan schema）")


class CreatePlanTool(Tool):
    """提交一个 plan，守护层即时校验。"""

    def __init__(self, state: PlanSessionState, auto_confirm: bool = True):
        super().__init__(
            name="create_plan",
            description="提交一个图表计划。守护层会即时校验：series_id 有效性、引用列存在性、"
                        "chart_type 白名单；通过或自动降级后入库。返回校验结果。",
            args_schema=CreatePlanInput,
            is_read_only=False, is_destructive=False, is_concurrency_safe=False,
            auto_confirm=auto_confirm,
        )
        self._state = state

    def check_permissions(self, ctx: ToolContext) -> Decision:
        return Decision(PermissionDecision.ALLOW)

    async def call(self, input_data: Dict[str, Any], ctx: ToolContext) -> ToolOutput:
        plan = dict(input_data.get("plan", {}))
        if not plan:
            return ToolOutput(success=False, error="plan 为空，请提供完整 plan JSON")

        if validate_one_plan(plan, self._state.catalog, self._state.profile, self._state.agent_logs,
                             self._state.tried):
            # plan 只引用 series_id，数据读取代码由守护层在生成阶段注入（单一真相）。
            # 禁止把读取代码塞进 plan：plan_details 会进入阶段 3 prompt。
            self._state.plans.append(plan)
            degraded = "（自动降级，仍会执行）" if plan.get("degraded") else ""
            return ToolOutput(
                success=True,
                output=f"plan {plan.get('plan_id', '?')} {plan.get('plan_name', '')} 已提交{degraded}。"
                       f"\n当前进度:\n{self._state.summary()}",
            )
        self._state.dropped.append(plan)
        return ToolOutput(
            success=False,
            error=f"plan {plan.get('plan_id', '?')} 被拒绝（见守护层日志），请修正后重试或换 series。"
                  f"\n当前进度:\n{self._state.summary()}",
        )