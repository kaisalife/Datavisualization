"""agent 流水线 · 图表规划阶段（v4 series 化）。

主路径：arun_with_tools 会话 —— agent 用 4 个工具自主浏览语义 series、
采样验证、逐个 create_plan 提交；守护层即时校验，plans 收于会话状态。
回退：会话异常 / 无目录 / 零 plan 时退回旧的一次 LLM 调用规划（chart_designer）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from prompts.agent_planning_prompt import build_planning_prompt
from service.monitoring.stage_timer import stage_timer
from service.observability import get_logger
from service.pipeline.plan_state import PlanSessionState
from service.pipeline.plan_toolpool import build_plan_tool_pool

logger = get_logger(__name__)

PLAN_MAX_ITERATIONS = 20


# ---------------------------------------------------------------- 旧路径（回退）
async def _legacy_plan_via_prompt(chat, model_, profile, catalog, agent_logs: list) -> list:
    """旧规划路径：一次 LLM 调用产出 plans JSON（agent 会话不可用时的回退）。"""
    from prompts.agent_prompt import get_agent_chart_designer_prompt
    from service.pipeline.plan_validator import validate_plans
    from service.runtime.utils import extract_json_from_response

    canonical_dataset = "(未提供)"
    if profile is not None:
        try:
            canonical_dataset = json.dumps(profile.to_prompt_dict(), ensure_ascii=False, indent=2)
        except Exception as e:
            agent_logs.append(f"⚠️ DataProfile 序列化失败: {e}")

    plan_input = {
        "data_file_path": ", ".join(model_.file_paths or []) if model_.file_paths else "",
        "data_preview": profile.to_prompt_str() if profile else "",
        "data_interface_info": "",
        "canonical_dataset": canonical_dataset,
        "series_index": catalog.to_index_prompt() if catalog is not None else "(未提供)",
        "user_chart_config": (model_.config or "(未提供)") if model_.config else "(未提供)",
        "user_prompt": model_.user_prompt,
        "mcp_prompt": getattr(model_, "mcp_prompt", "") or "",
        "skill_prompt": getattr(model_, "skill_prompt", "") or "",
    }
    try:
        plan_result = await chat.ainvoke(get_agent_chart_designer_prompt().invoke(plan_input))
        plan_content = plan_result["content"] if isinstance(plan_result, dict) else str(plan_result)
    except Exception as e:
        agent_logs.append(f"⚠️ 规划失败({e})，返回空")
        return []
    plans_data = extract_json_from_response(plan_content)
    if isinstance(plans_data, list):
        plans_data = {"plans": plans_data}
    plans = plans_data.get("plans", []) if isinstance(plans_data, dict) else []
    if not plans:
        return []
    return validate_plans(plans, catalog, profile, agent_logs)


def _persist_plans(plans: list, output_folder: Path, agent_logs: list) -> None:
    """all_plans.json 落盘。"""
    try:
        (output_folder / "all_plans.json").write_text(
            json.dumps({"plans": plans}, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        logger.warning("all_plans.json 落盘失败", error=str(e))
    agent_logs.append(f"📋 plan 层规划 {len(plans)} 个图表（已校验）")


# ---------------------------------------------------------------- 主路径
async def run_plan_stage(
    chat,
    *,
    model_,
    profile,
    output_folder: Path,
    task_id: str | None,
    catalog,
    agent_logs: list,
) -> list[dict]:
    """执行图表规划阶段（阶段 2 agent 会话，v4）。

    Args:
        chat: 已初始化 BaseAgent（须有 arun_with_tools）
        model_: GenerateChartWithPromptRequest
        profile: DataProfile
        output_folder: 输出目录（all_plans.json 落盘处）
        task_id: 任务ID（计时）
        catalog: SeriesCatalog | None
        agent_logs: 前端展示日志，就地追加

    Returns:
        校验后的 plans 列表（可能为空 -> 调用方走 agent 自主规划）
    """
    if catalog is None or not catalog.series:
        agent_logs.append("⚠️ 无系列目录，回退旧规划路径")
        plans = await _legacy_plan_via_prompt(chat, model_, profile, catalog, agent_logs)
        _persist_plans(plans, output_folder, agent_logs)
        return plans

    state = PlanSessionState(catalog=catalog, agent_logs=agent_logs, profile=profile)
    try:
        tools = build_plan_tool_pool(state)
        message = build_planning_prompt().invoke({
            "user_prompt": model_.user_prompt,
            "profile_str": profile.to_prompt_str() if profile else "(未提供)",
            "series_index": catalog.to_index_prompt(),
        })
        with stage_timer.stage(task_id, "plan", "图表规划(agent)"):
            result = await chat.arun_with_tools(
                message, max_iterations=PLAN_MAX_ITERATIONS, tools=tools
            )
        logs = result.get("agent_logs", []) if isinstance(result, dict) else []
        for line in logs:
            agent_logs.append(f"📋 [plan agent] {line}")
    except Exception as e:
        logger.warning("plan agent 会话异常，回退旧路径", error=str(e))
        agent_logs.append(f"⚠️ plan agent 会话失败({e})，回退旧规划路径")
        plans = await _legacy_plan_via_prompt(chat, model_, profile, catalog, agent_logs)
        _persist_plans(plans, output_folder, agent_logs)
        return plans

    plans = state.plans
    for dropped in state.dropped:
        agent_logs.append(f"❌ plan {dropped.get('plan_id', '?')} {dropped.get('plan_name', '')} 被守护层拒绝")

    if not plans:
        agent_logs.append("⚠️ agent 未提交有效 plan，回退旧规划路径")
        plans = await _legacy_plan_via_prompt(chat, model_, profile, catalog, agent_logs)

    _persist_plans(plans, output_folder, agent_logs)
    return plans


def build_default_plan(model_) -> dict:
    """plan 阶段无产出时的默认自主规划（无 series，生成阶段走兼容路径）。"""
    return [{
        "plan_id": "1",
        "plan_name": "自主图表",
        "chart_type": "auto",
        "chart_title": model_.user_prompt[:30],
        "use_column_names": True,
        "data_interface": {"available": False},
    }]