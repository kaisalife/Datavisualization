"""Agent loop 自主流水线。

用 BaseAgent.arun_with_tools + 本地工具（ReadDataFileTool + 增强 RunCodeTool），
LLM 自主完成"读数据 -> 生成 pyecharts 代码 -> 执行 -> 看输出迭代"。
作为 service_main 的 viz_mode=agent 路径，替换固定 plan->generate->debug 流水线。

返回结构兼容 common.py（successful_charts/failed_plans/agent_logs）。
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List

from Entity.plan_models import plan_get
from service.monitoring import trace
from service.monitoring.stage_timer import stage_timer
from service.runtime.context_card import build_context_cards, write_context_cards


def _check_cancelled(task_id):
    """检查任务是否被取消。"""
    if task_id is None:
        return False
    from api.common import is_cancelled
    return is_cancelled(task_id)


async def execute_plans_concurrently(
    plans: list,
    *,
    task_id: str | None,
    concurrency: int,
    runner,
) -> tuple[list[dict], bool]:
    """并发执行 plans，保持输入顺序返回结果。

    Args:
        plans: plan 列表
        task_id: 用于取消检查
        concurrency: 并发度（<=0 时按 1）
        runner: ``async def runner(idx, plan) -> dict``，结果至少包含
            ``{"idx": int, "cancelled": bool, "logs": [...]}``

    Returns:
        (按 idx 排序的结果列表, 是否有 plan 因取消未执行)
    """
    semaphore = asyncio.Semaphore(max(1, int(concurrency)))

    async def _run(idx: int, plan_item):
        async with semaphore:
            if _check_cancelled(task_id):
                return {"idx": idx, "cancelled": True, "logs": []}
            return await runner(idx, plan_item)

    results = await asyncio.gather(*(_run(idx, plan) for idx, plan in enumerate(plans)))
    cancelled = any(item.get("cancelled") for item in results)
    return sorted(results, key=lambda item: item["idx"]), cancelled


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

    # RAG 模型加载（约 8s，首次任务）与规划并行：规划等 LLM 的时间足够覆盖加载，
    # 不再让图表阶段先干等。加载失败只记 warning，图表继续无 RAG 生成。
    async def _load_retriever_async():
        def _sync():
            from RAG.RAG_main import get_default_retriever
            return get_default_retriever()

        try:
            return await asyncio.to_thread(_sync)
        except Exception as exc:
            agent_logs.append(f"⚠️ RAG 初始化失败: {exc}")
            return None

    rag_task = asyncio.create_task(_load_retriever_async())

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

    engine = QueryEngine(chat_model=chat, model_name=model_.model_type or "")
    generate_prompt = get_agent_generate_chart_prompt()
    debug_prompt = get_agent_debug_chart_prompt()

    rag_retriever = await rag_task

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

    # 图表之间互不依赖：并发执行（与 legacy 流水线一致），串行会把 N 张图的总耗时
    # 变成累加。并发度读 CHART_CONCURRENCY（默认 3），也受 plan 数量约束。
    from service.runtime.utils import get_env_int

    concurrency = max(1, min(len(plans), get_env_int("CHART_CONCURRENCY", 3)))
    agent_logs.append(f"⚡ 图表并发度: {concurrency}")

    async def _execute_plan(idx: int, plan_item: dict) -> dict:
        plan_name = plan_get(plan_item, "plan_name", f"图表{idx + 1}")
        logs = [f"📊 执行 plan {idx + 1}/{len(plans)}: {plan_name}"]

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
                    user_prompt=model_.user_prompt or "",
                )
        except Exception as e:
            success, chart_path, code, error = False, "", "", f"generate_single_chart 异常: {e}"

        generation = plan_get(plan_item, "generation", {}) or {}
        validation = generation.get("validation", {}) if isinstance(generation, dict) else {}
        if success and chart_path:
            logs.append(f"✅ plan {idx + 1} 成功: {chart_path}")
            return {
                "idx": idx,
                "cancelled": False,
                "success": True,
                "chart": {
                    "plan": plan_item,
                    "chart_path": chart_path,
                    "code": code,
                    "generation": generation,
                    "validation": validation,
                },
                "logs": logs,
            }

        codes = [e.get("code") for e in validation.get("errors", []) if e.get("code")]
        code_text = f" [{', '.join(codes)}]" if codes else ""
        logs.append(f"❌ plan {idx + 1} 失败{code_text}: {(error or '未知')[:100]}")
        return {
            "idx": idx,
            "cancelled": False,
            "success": False,
            "failed": {
                "plan": plan_item,
                "error": error,
                "generation": generation,
                "validation": validation,
            },
            "logs": logs,
        }

    results, cancelled = await execute_plans_concurrently(
        plans,
        task_id=task_id,
        concurrency=concurrency,
        runner=_execute_plan,
    )

    for item in results:
        agent_logs.extend(item["logs"])
        if item.get("success") and item.get("chart"):
            successful_charts.append(item["chart"])
        elif item.get("failed"):
            failed_plans.append(item["failed"])

    if cancelled:
        agent_logs.append("❌ 任务已被用户取消")
        raise RuntimeError("Task cancelled by user")

    context_cards = build_context_cards(
        getattr(model_, "user_prompt", ""),
        profile,
        plans,
        successful_charts,
        failed_plans,
    )
    write_context_cards(output_folder, context_cards)

    return {
        "successful_charts": successful_charts,
        "failed_plans": failed_plans,
        "agent_logs": agent_logs,
        "context_cards": context_cards,
    }
