"""Agent loop 自主流水线。

用 BaseAgent.arun_with_tools + 本地工具（ReadDataFileTool + 增强 RunCodeTool），
LLM 自主完成"读数据 -> 生成 pyecharts 代码 -> 执行 -> 看输出迭代"。
作为 service_main 的 viz_mode=agent 路径，替换固定 plan->generate->debug 流水线。

返回结构兼容 common.py（successful_charts/failed_plans/agent_logs）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from service.monitoring import trace


def _check_cancelled(task_id):
    """检查任务是否被取消。"""
    if task_id is None:
        return False
    from api.common import is_cancelled
    return is_cancelled(task_id)


@trace(category="pipeline")
async def run_agent_pipeline(
    chat,
    model_,
    profile,
    output_folder: Path,
    task_id: str | None = None,
    max_iterations: int = 18,
) -> Dict[str, Any]:
    """agent loop 自主流水线。

    Args:
        chat: 已初始化的 BaseAgent
        model_: GenerateChartWithPromptRequest
        profile: DataProfile（含 duckdb_path/table_name/to_prompt_dict）
        output_folder: 输出目录
        task_id: 任务ID（取消检查）
        max_iterations: 最大工具调用轮次

    Returns:
        {"successful_charts": [...], "failed_plans": [...], "agent_logs": [...]}
    """
    agent_logs: List[str] = []
    agent_logs.append("🤖 启动 Agent 自主流水线")

    charts_folder = output_folder / "charts"
    charts_folder.mkdir(parents=True, exist_ok=True)

    # 记录执行前已有 HTML（用于识别新增）
    before_files = {p.name for p in charts_folder.glob("*.html")}

    # 构建本地工具池（延迟 import 避免循环）
    from agent.tools.read_data_file_tool import ReadDataFileTool
    from agent.tools.run_code_tool import RunCodeTool
    from agent.tools.base import ToolContext
    from agent.tool_adapter import wrap_local_tools
    from service.chart_generator import _RENDER_HEADER
    from prompts.agent_autonomous_prompt import get_agent_autonomous_prompt

    file_paths = model_.file_paths or []
    duckdb_path = profile.duckdb_path if profile else ""
    table_name = profile.table_name if profile else ""

    ctx = ToolContext(auto_confirm=True, working_dir=str(output_folder))
    local_tools = [
        ReadDataFileTool(auto_confirm=True),
        RunCodeTool(
            auto_confirm=True,
            output_dir=str(charts_folder),
            duckdb_path=duckdb_path,
            prelude=_RENDER_HEADER,
        ),
    ]
    tools = wrap_local_tools(local_tools, ctx)
    agent_logs.append(f"🔧 已装载工具: {[t.name for t in tools]}")

    # 构造自主 prompt（注入 DataProfile 语义特征）
    canonical_dataset = "(未提供)"
    if profile is not None:
        try:
            canonical_dataset = json.dumps(profile.to_prompt_dict(), ensure_ascii=False, indent=2)
        except Exception as e:
            agent_logs.append(f"⚠️ DataProfile 序列化失败: {e}")

    prompt = get_agent_autonomous_prompt().invoke({
        "file_paths": ", ".join(file_paths) if file_paths else "(无)",
        "table_name": table_name,
        "canonical_dataset": canonical_dataset,
        "user_prompt": model_.user_prompt,
        "output_dir": str(charts_folder),
    })

    if _check_cancelled(task_id):
        agent_logs.append("❌ 任务已被用户取消")
        raise RuntimeError("Task cancelled by user")

    # 执行 agent loop
    try:
        result = await chat.arun_with_tools(
            prompt, max_iterations=max_iterations, tools=tools
        )
    except Exception as e:
        agent_logs.append(f"❌ Agent 执行异常: {e}")
        return {
            "successful_charts": [],
            "failed_plans": [{"plan": {}, "error": f"Agent 异常: {e}"}],
            "agent_logs": agent_logs,
        }

    # 合并 agent 日志
    agent_logs.extend(result.get("agent_logs", []))
    agent_logs.append(f"📊 Agent 完成，工具调用 {len(result.get('tool_calls', []))} 次")

    # 扫描新增 HTML 作为成功图表
    after_files = {p.name for p in charts_folder.glob("*.html")}
    new_files = sorted(after_files - before_files)

    successful_charts = []
    for fname in new_files:
        chart_path = str(charts_folder / fname)
        successful_charts.append({
            "plan": {"plan_name": fname, "chart_type": "auto"},
            "chart_path": chart_path,
        })

    if successful_charts:
        agent_logs.append(
            f"✅ 生成 {len(successful_charts)} 个图表: "
            f"{[c['plan']['plan_name'] for c in successful_charts]}"
        )
    else:
        agent_logs.append("⚠️ 未生成任何图表 HTML")

    failed_plans = []
    if not successful_charts:
        failed_plans.append({"plan": {}, "error": "Agent 未产出图表"})

    return {
        "successful_charts": successful_charts,
        "failed_plans": failed_plans,
        "agent_logs": agent_logs,
    }
