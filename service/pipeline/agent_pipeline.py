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
from service.monitoring.stage_timer import stage_timer


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
    # 注入 task_id 到 chat + contextvar，用于 token 统计推送
    chat.task_id = task_id or ""
    from service.monitoring.tracer import _task_id
    _task_id.set(task_id or "")
    agent_logs: List[str] = []
    agent_logs.append("🤖 启动 Agent 自主流水线")

    charts_folder = output_folder / "charts"
    charts_folder.mkdir(parents=True, exist_ok=True)

    file_paths = model_.file_paths or []
    catalog = profile.series_catalog if profile is not None else None

    # 语义 series 目录：由预处理阶段确定性拆分并落盘（v4，无 SQL recipe）。
    # 已在 ingest 阶段生成 manifest.json；此处仅从 profile 取出 catalog。
    if catalog is not None:
        n = len(catalog.series)
        agent_logs.append(f"🧾 语义 series 目录: {n} 条数据系列已就绪")

    # 构建本地工具池（P0.4 debug agent 环节使用）
    from service.pipeline.agent_toolpool import build_agent_tool_pool
    tools = build_agent_tool_pool(output_folder, charts_folder)
    agent_logs.append(f"🔧 已装载工具: {[t.name for t in tools]}")

    # ==== 阶段 1: 图表规划（已拆至 agent_plan_stage.py：prompt 注入 series 索引 + 确定性校验）====
    from service.pipeline.agent_plan_stage import run_plan_stage
    plans = await run_plan_stage(
        chat,
        model_=model_,
        profile=profile,
        output_folder=output_folder,
        task_id=task_id,
        catalog=catalog,
        agent_logs=agent_logs,
    )

    # ==== 阶段 2: 逐个 plan 执行（每个图表单独 task，只注入该 plan 规范）====
    from service.pipeline.chart_generator import generate_single_chart
    from prompts.agent_prompt import get_agent_generate_chart_prompt, get_agent_debug_chart_prompt
    from service.runtime.query_engine import QueryEngine
    from RAG.RAG_main import RAGRetriever

    engine = QueryEngine(chat_model=chat, model_name=model_.model_type or "")
    generate_prompt = get_agent_generate_chart_prompt()
    debug_prompt = get_agent_debug_chart_prompt()

    try:
        rag_retriever = RAGRetriever()
    except Exception as e:
        agent_logs.append(f"⚠️ RAG 初始化失败: {e}")
        rag_retriever = None

    dataset_summary_json = "(未提供)"
    if profile is not None:
        try:
            dataset_summary_json = json.dumps({
                "source_kind": profile.source_kind,
                "table_name": profile.table_name,
                "columns": profile.schema,
                "row_count": profile.row_count,
            }, ensure_ascii=False, indent=2)
        except Exception:
            pass

    user_chart_config_json = (model_.config or "(未提供)") if model_.config else "(未提供)"

    # 若 plan 未产出，构造默认 plan（agent 自主）
    if not plans:
        from service.pipeline.agent_plan_stage import build_default_plan
        plans = build_default_plan(model_)
        agent_logs.append("⚠️ 无 plan，使用自主规划")

    successful_charts = []
    failed_plans = []

    for idx, plan_item in enumerate(plans):
        if _check_cancelled(task_id):
            agent_logs.append("❌ 任务已被用户取消")
            raise RuntimeError("Task cancelled by user")

        plan_name = plan_item.get("plan_name", f"图表{idx + 1}")
        agent_logs.append(f"📊 执行 plan {idx + 1}/{len(plans)}: {plan_name}")

        try:
            with stage_timer.stage(
                task_id, f"chart_{idx + 1}", f"图表 {idx + 1}/{len(plans)}: {plan_name}"
            ):
                success, chart_path, code, error = await generate_single_chart(
                    chat=chat,
                    plan=plan_item,
                    data_file_path=", ".join(file_paths) if file_paths else "",
                    data_preview=profile.to_prompt_str() if profile else "",
                    output_folder=output_folder,
                    engine=engine,
                    generate_prompt=generate_prompt,
                    debug_prompt=debug_prompt,
                    retriever=rag_retriever,
                    max_retries=3,
                    dataset_summary=dataset_summary_json,
                    catalog=catalog,
                    user_config=user_chart_config_json,
                )
        except Exception as e:
            success, chart_path, code, error = False, "", "", f"generate_single_chart 异常: {e}"

        if success and chart_path:
            successful_charts.append({"plan": plan_item, "chart_path": chart_path, "code": code})
            agent_logs.append(f"✅ plan {idx + 1} 成功: {chart_path}")
        else:
            failed_plans.append({"plan": plan_item, "error": error})
            agent_logs.append(f"❌ plan {idx + 1} 失败: {(error or '未知')[:100]}")

    return {
        "successful_charts": successful_charts,
        "failed_plans": failed_plans,
        "agent_logs": agent_logs,
    }
