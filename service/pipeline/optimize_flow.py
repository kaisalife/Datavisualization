"""单图优化的任务编排（对应 service_main 的二次优化入口）。

流程：载配置 → 初始化 agent → 按 chart_id 反查资产 → 读原 plan/代码 →
优化 agent（RAG 知识库 + 数据证据）→ 重新渲染 → 登记新资产 → 汇总返回。

返回结构与 service_main 对齐（successful_charts / failed_plans / agent_logs），
复用既有任务状态与 WebSocket 推送管线（``_run_optimize_in_executor``）。
"""
from __future__ import annotations

import json
from pathlib import Path

from service.observability import get_logger
from service.runtime.chart_assets import find_asset_by_chart_id, load_assets, next_optimize_version, record_chart
from service.runtime.config import load_config
from service.runtime.exceptions import ConfigError
from service.runtime.utils import get_env_int

try:
    from Entity.plan_models import plan_get
except ImportError:
    from ..plan_models import plan_get  # type: ignore  # pragma: no cover

logger = get_logger(__name__)


async def _init_chat(model_, mcp_config, agent_logs: list):
    """与 service_main 同构的 agent 初始化（单独实现，保持两者解耦）。"""
    from service.runtime.config import get_agent_class

    chat = get_agent_class(model_.model_type, model_.model_url, model_.model_api_key, mcp_config)
    agent_logs.append("🔧 正在初始化优化 agent...")
    await chat.initialize()
    agent_logs.append("✅ 优化 agent 初始化成功")
    return chat


def _dataset_summary_from_data(data_path: str) -> str:
    """缺 DataProfile 时从 series parquet 现算 schema 摘要（确定性、无 LLM）。"""
    if not data_path:
        return "(未提供)"
    try:
        import pandas as pd

        df = pd.read_parquet(data_path)
        schema = [
            {"name": str(col), "type": str(dtype)}
            for col, dtype in zip(df.columns, df.dtypes)
        ]
        return json.dumps(
            {"rows": int(len(df)), "columns": schema},
            ensure_ascii=False, indent=2,
        )
    except Exception as e:
        logger.warning("优化数据摘要生成失败", data_path=data_path, error=str(e))
        return "(未提供)"


def _strip_injection_header(code: str) -> str:
    """原始 success 代码去掉守护层注入的 series 读取段（进 prompt 前剥离）。

    注入段是确定性产物（优化时会重新注入），留在"原始成功代码"里只会诱导
    agent 复制它，进而与优化后的注入段重复加载 parquet。
    """
    if not code.lstrip().startswith("# --- series:"):
        return code
    marker = "# --- end series ---"
    idx = code.find(marker)
    if idx == -1:
        return code
    return code[idx + len(marker):].lstrip("\n")


def _serialize_result(item: dict | None, chart_path: str, code: str) -> dict:
    return {
        "plan": item or {},
        "chart_path": chart_path,
        "code": code,
        "generation": {},
        "validation": {},
    }


async def optimize_chart_main(model_, config_path=None, task_id=None):
    """优化单张已生成图表（任务级入口）。

    Args:
        model_: OptimizeChartRequest（chart_id + user_prompt + 模型配置）
        config_path: 配置文件路径（None 用默认）
        task_id: 任务 ID（用于资产登记与取消检查）

    Returns:
        dict: {"successful_charts", "failed_plans", "agent_logs"}
            （形状与 service_main 对齐，供任务状态与 WS 管线直接复用）
    """
    agent_logs: list[str] = []
    agent_logs.append("🛠️ 图表二次优化流水线")
    config = load_config(config_path)

    chat = await _init_chat(model_, config["mcp_config"], agent_logs)
    if task_id:
        from service.monitoring.tracer import _task_id

        _task_id.set(task_id)

    asset = find_asset_by_chart_id(model_.chart_id)
    if asset is None:
        raise ConfigError(f"未找到可优化的图表资产: {model_.chart_id}（不存在或已清理）")
    output_folder = Path(asset["output_folder"])
    plan_file = output_folder / "plans" / f"plan_{asset['plan_id']}.json"
    if not plan_file.is_file():
        raise ConfigError(f"原 plan 文件缺失: {plan_file.name}（无法读取原始计划上下文）")
    try:
        plan = json.loads(plan_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise ConfigError(f"原 plan 文件解析失败: {e}") from e

    code_path = Path(asset.get("code_path") or "")
    if not code_path.is_file():
        raise ConfigError(f"原始成功代码缺失: {code_path}")
    original_code = _strip_injection_header(code_path.read_text(encoding="utf-8"))

    data_path = str(asset.get("data_path") or "")
    if not data_path:
        raise ConfigError("该图表为自备读取模式（无 series 数据文件），暂不支持二次优化")
    if not Path(data_path).is_file():
        raise ConfigError(f"series 数据文件缺失: {data_path}（会话目录可能已被清理）")

    agent_logs.append(
        f"🎯 优化目标: {asset.get('plan_name') or asset['chart_id']}"
        f"（{asset.get('chart_type') or '?'}, 版本 {asset.get('version', 0)}）"
    )

    # RAG 知识库（pyecharts API 示例）：与生成阶段同一检索器，进程内复用
    retriever = None
    try:
        from RAG.RAG_main import get_default_retriever

        retriever = get_default_retriever()
        agent_logs.append("📚 RAG 知识库就绪（pyecharts API 示例）")
    except Exception as e:
        logger.warning("优化 RAG 检索器初始化失败", error=str(e))
        agent_logs.append("⚠️ RAG 知识库不可用，仅凭模型知识优化")

    from service.pipeline.chart_optimizer import optimize_single_chart

    ok, chart_path, code, plan_id, error = await optimize_single_chart(
        chat,
        user_prompt=model_.user_prompt,
        plan=plan,
        original_code=original_code,
        chart_id=asset["chart_id"],
        data_path=data_path,
        output_folder=output_folder,
        retriever=retriever,
        dataset_summary=_dataset_summary_from_data(data_path),
        max_attempts=get_env_int("OPTIMIZE_MAX_ATTEMPTS", 3),
    )

    if not ok:
        agent_logs.append(f"❌ 优化失败: {error[:200]}")
        return {
            "successful_charts": [],
            "failed_plans": [{"plan": plan, "error": error}],
            "agent_logs": agent_logs,
        }

    from service.monitoring.tracer import _conversation_id as _ctx_conversation_id

    version = next_optimize_version(load_assets(output_folder), asset["chart_id"])
    record_chart(
        output_folder,
        task_id=task_id or "",
        conversation_id=_ctx_conversation_id.get() or "",
        plan={**plan, "plan_id": plan_id},
        chart_path=chart_path,
        code_path=str(output_folder / "code" / f"code_{plan_id}_success.py"),
        data_path=data_path,
        origin_chart_id=asset["chart_id"],
        version=version,
        extra={"optimize_prompt": model_.user_prompt[:200]},
    )
    agent_logs.append(f"✅ 优化完成: {Path(chart_path).name}（版本 {version}，原图保留）")

    plan_snapshot = {**plan, "plan_id": plan_id, "optimization_of": asset["chart_id"]}
    return {
        "successful_charts": [_serialize_result(plan_snapshot, chart_path, code)],
        "failed_plans": [],
        "agent_logs": agent_logs,
    }
