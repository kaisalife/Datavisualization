"""图表并发执行：按 plans 调度 generate_single_chart，汇总成功/失败。

流程：
1. 初始化生成/调试提示 + RAG 检索器
2. 按执行顺序并发跑各 plan（信号量限流，支持取消检查）
3. 分类 gather 结果并输出执行总结
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from service.pipeline.chart_generator import generate_single_chart
from service.observability import get_logger

logger = get_logger(__name__)

try:
    from prompts.agent_prompt import get_agent_debug_chart_prompt, get_agent_generate_chart_prompt
    from RAG.RAG_main import RAGRetriever
    from Entity.plan_models import plan_get
except ImportError:
    from prompts.agent_prompt import get_agent_debug_chart_prompt, get_agent_generate_chart_prompt
    from RAG.RAG_main import RAGRetriever
    from ..plan_models import plan_get


def _check_cancelled(task_id):
    """检查任务是否被取消。"""
    if task_id is None:
        return False
    from api.common import is_cancelled
    return is_cancelled(task_id)


def _resolve_concurrency(config: dict) -> tuple[int, int]:
    """解析并发度与重试次数：环境变量 > config.chart_generation > 默认值。"""
    chart_cfg = config.get("chart_generation", {}) if isinstance(config, dict) else {}
    try:
        concurrency = max(1, int(os.environ.get(
            "CHART_CONCURRENCY", chart_cfg.get("concurrency", 3)
        )))
    except (ValueError, TypeError):
        concurrency = 3
    try:
        max_retries = max(1, int(os.environ.get(
            "CHART_MAX_RETRIES", chart_cfg.get("max_retries", 3)
        )))
    except (ValueError, TypeError):
        max_retries = 3
    return concurrency, max_retries


def _build_dataset_summary(profile) -> str:
    """生成简化的 dataset_summary（列 schema），供每个 chart 复用。"""
    if profile is None:
        return "(未提供)"
    try:
        return json.dumps({
            "source_kind": profile.source_kind,
            "table_name": profile.table_name,
            "columns": profile.schema,
            "row_count": profile.row_count,
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("dataset_summary 生成失败", error=str(e))
        return "(未提供)"


async def execute_chart_plans(
    chat,
    engine,
    *,
    plans: list,
    profile,
    data_file_path: str,
    data_preview: str,
    output_folder: Path,
    user_config_json: str,
    config: dict,
    task_id=None,
    agent_logs: list,
) -> tuple[list, list]:
    """并发执行图表计划。

    Args:
        chat: 已初始化的 BaseAgent
        engine: QueryEngine（生成代码时复用其会话）
        plans: 计划列表（按 execution_order 排序在内部完成）
        profile: DataProfile（提供 duckdb_path/table_name/dataset_summary）
        data_file_path: 源路径（兼容旧字段）
        data_preview: 数据预览文本
        output_folder: 输出目录
        user_config_json: 用户自定义图表配置 JSON 串
        config: 服务配置（读 chart_generation 并发参数）
        task_id: 任务ID（取消检查）
        agent_logs: 前端展示日志，就地追加

    Returns:
        (successful_charts, failed_plans)
    """
    if _check_cancelled(task_id):
        agent_logs.append("❌ 任务已被用户取消")
        raise RuntimeError("Task cancelled by user")

    logger.info("初始化生成和调试提示")
    generate_prompt = get_agent_generate_chart_prompt()
    debug_prompt = get_agent_debug_chart_prompt()
    logger.info("提示初始化完成")

    logger.info("初始化 RAG 检索器")
    try:
        rag_retriever = RAGRetriever()
        logger.info("RAG 检索器初始化成功")
    except Exception as e:
        logger.warning("RAG 检索器初始化失败", error=str(e))
        rag_retriever = None

    dataset_summary_json = _build_dataset_summary(profile)
    catalog = profile.series_catalog if profile is not None else None

    ordered_plans = sorted(plans, key=lambda x: plan_get(x, "execution_order", 0))
    concurrency, max_retries = _resolve_concurrency(config)
    semaphore = asyncio.Semaphore(concurrency)
    logger.info("plans 并发度", concurrency=concurrency, max_retries=max_retries)
    agent_logs.append(f"🚀 plans 并发度: {concurrency}, max_retries: {max_retries}")

    if _check_cancelled(task_id):
        agent_logs.append("❌ 任务已被用户取消")
        raise RuntimeError("Task cancelled by user")

    async def _run_one(plan_item: dict):
        async with semaphore:
            if engine.aborted:
                logger.warning("QueryEngine 已中止，跳过 plan")
                return plan_item, False, "", "aborted"
            success, chart_path, code, error = await generate_single_chart(
                chat=chat,
                plan=plan_item,
                data_file_path=data_file_path,
                data_preview=data_preview,
                output_folder=output_folder,
                engine=engine,
                generate_prompt=generate_prompt,
                debug_prompt=debug_prompt,
                retriever=rag_retriever,
                max_retries=max_retries,
                dataset_summary=dataset_summary_json,
                catalog=catalog,
                user_config=user_config_json,
            )
            return plan_item, success, chart_path, code, error

    results = await asyncio.gather(
        *(_run_one(p) for p in ordered_plans),
        return_exceptions=True,
    )

    successful_charts = []
    failed_plans = []
    for res in results:
        if isinstance(res, Exception):
            failed_plans.append({"plan": {}, "error": f"gather 异常: {res}"})
            continue
        plan_item, success, chart_path, code, error = res
        if success and chart_path:
            successful_charts.append({
                "plan": plan_item,
                "chart_path": chart_path,
                "code": code,
            })
        else:
            failed_plans.append({
                "plan": plan_item,
                "error": error,
            })
    return successful_charts, failed_plans


def log_execution_summary(successful_charts: list, failed_plans: list, agent_logs: list):
    """输出执行总结（日志 + agent_logs）。"""
    logger.info("执行总结")
    logger.info("成功计数", count=len(successful_charts))
    logger.info("失败计数", count=len(failed_plans))
    agent_logs.append("📊 执行总结")
    agent_logs.append(f"✅ 成功: {len(successful_charts)} 个图表")
    agent_logs.append(f"❌ 失败: {len(failed_plans)} 个计划")

    if successful_charts:
        logger.info("成功的图表列表", count=len(successful_charts))
        for idx, item in enumerate(successful_charts, 1):
            logger.info("成功图表", index=idx, plan_name=plan_get(item["plan"], "plan_name", ""), chart_path=str(item["chart_path"]))
        for idx, item in enumerate(successful_charts, 1):
            agent_logs.append(f"  📁 图表 {idx}: {plan_get(item['plan'], 'plan_name', '?')} -> {item['chart_path']}")

    if failed_plans:
        logger.warning("失败的计划列表", count=len(failed_plans))
        for idx, item in enumerate(failed_plans, 1):
            plan_name = plan_get(item["plan"], "plan_name", "unknown") if item["plan"] else "unknown"
            logger.warning("失败计划", index=idx, plan_name=plan_name, error=str(item["error"])[:100])
            agent_logs.append(f"  ❌ 计划 {idx}: {plan_name} 失败: {item['error'][:100]}")
