"""阶段 2 计划 agent 工具：试查与提交 plan（v4）。

- preview_series: 只读采样某条语义 series（确认数据可行）
- create_plan:    提交一个 plan（即时确定性校验，通过/降级/丢弃当场反馈给 agent）
"""
from __future__ import annotations

from typing import Any, Dict

from pydantic import BaseModel, Field

from agent.tools.base import Decision, PermissionDecision, Tool, ToolContext, ToolOutput
from agent.tools.read_table_sample_tool import ReadSeriesSampleTool
from service.pipeline.chart_recommend import (
    chart_family,
    normalize_chart_type,
    recommend_chart_types,
)
from service.pipeline.plan_state import PlanSessionState
from service.pipeline.plan_validator import validate_one_plan


def _summarize_items(items) -> str:
    """把 assumptions / clarification 里的字符串或对象压成一行提示。"""
    if not isinstance(items, list):
        return str(items or "")
    parts = []
    for item in items:
        if isinstance(item, dict):
            text = (
                item.get("description")
                or item.get("question")
                or item.get("kind")
                or item.get("text")
                or ""
            )
        else:
            text = str(item)
        if text:
            parts.append(str(text))
    return "；".join(parts)


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

            # 即时给出数据形态建议：agent 可当场修正，最终守护层还会再校正一次。
            advice_note = ""
            series = self._state.catalog.by_id(plan.get("series_id", ""))
            if series is not None:
                advice = recommend_chart_types(
                    series, self._state.user_prompt, load_if_missing=False
                )
                current = normalize_chart_type(plan.get("chart_type"))
                recommended_list = advice.get("recommended", [])
                recommended = {
                    normalize_chart_type(item) for item in recommended_list
                }
                accepted = recommended | {
                    normalize_chart_type(item) for item in advice.get("alternatives", [])
                }
                explicit = {
                    normalize_chart_type(item) for item in advice.get("explicit_types", [])
                }
                primary_family = chart_family(recommended_list[0]) if recommended_list else ""
                # 时间序列画柱/饼即使落在"备选"里也要提醒；其他备选类型是合理的
                mismatch = current not in accepted or (
                    primary_family == "trend" and chart_family(current) != "trend"
                )
                if current and mismatch and current not in explicit:
                    shape = advice.get("shape_summary") or "数据形态"
                    suggested = "/".join(advice.get("recommended", []))
                    advice_note = (
                        f"\n💡 {shape}：建议 {suggested}。若当前类型不是用户明确要求，"
                        "最终守护层会按数据形态校正。"
                    )

            contract_note = ""
            assumptions = plan.get("assumptions") or []
            if assumptions:
                contract_note += f"\n📝 假设: {_summarize_items(assumptions)}"
            clarification = plan.get("clarification") or []
            if clarification:
                contract_note += f"\n❓ 待确认: {_summarize_items(clarification)}"
            validation = plan.get("validation") or {}
            warnings = validation.get("warnings") or []
            if warnings:
                contract_note += f"\n⚠️ 校验提示: {_summarize_items(warnings)}"

            return ToolOutput(
                success=True,
                output=f"plan {plan.get('plan_id', '?')} {plan.get('plan_name', '')} 已提交{degraded}。"
                       f"{advice_note}{contract_note}\n当前进度:\n{self._state.summary()}",
            )
        self._state.dropped.append(plan)
        return ToolOutput(
            success=False,
            error=f"plan {plan.get('plan_id', '?')} 被拒绝（见守护层日志），请修正后重试或换 series。"
                  f"\n当前进度:\n{self._state.summary()}",
        )