"""图表计划生成：调用 LLM 产出 plans，解析并落盘。

流程：
1. 合并项目记忆 + 用户 skill_prompt
2. DataProfile 转 canonical_dataset 注入 planner
3. QueryEngine 调 LLM 生成计划
4. 解析 JSON（兼容裸数组），保存 plan_response.txt / all_plans.json
"""
from __future__ import annotations

import json
from pathlib import Path

from service.runtime.exceptions import ConfigError
from service.runtime.memory.project_memory import get_project_memory
from service.observability import get_logger
from service.runtime.utils import extract_json_from_response

try:
    from Entity.plan_models import parse_plans
except ImportError:
    from ..plan_models import parse_plans

try:
    from service.data_ingestion.series.models import SeriesCatalog
except ImportError:
    from ..data_ingestion.series.models import SeriesCatalog

logger = get_logger(__name__)

try:
    from prompts.agent_prompt import get_agent_chart_designer_prompt
except ImportError:
    from prompts.agent_prompt import get_agent_chart_designer_prompt


async def generate_chart_plans(
    engine,
    *,
    model_,
    profile,
    data_preview: str,
    data_file_path: str,
    output_folder: Path,
    user_chart_config_json: str,
    agent_logs: list,
) -> list:
    """生成图表计划列表。

    Args:
        engine: QueryEngine（执行 LLM 调用）
        model_: GenerateChartWithPromptRequest
        profile: DataProfile（转 canonical_dataset）
        data_preview: 数据预览文本
        data_file_path: 源路径（兼容旧字段）
        output_folder: 计划文件落盘目录
        user_chart_config_json: 用户自定义图表配置 JSON 串
        agent_logs: 前端展示日志，就地追加

    Returns:
        plans 列表（未排序，执行排序由 chart_executor 负责）

    Raises:
        ConfigError: LLM 响应无法解析为计划
    """
    logger.info("步骤 1: 生成图表计划")
    agent_logs.append("📋 步骤 1: 生成图表计划")

    project_memory = get_project_memory()
    skill_prompt = (project_memory + "\n" + model_.skill_prompt) if project_memory else model_.skill_prompt

    # DataProfile 通过 canonical_dataset 注入 planner
    canonical_dataset_json = "(未提供)"
    if profile is not None:
        try:
            canonical_dataset_json = json.dumps(profile.to_prompt_dict(), ensure_ascii=False, indent=2)
            logger.info("canonical_dataset 生成成功", length=len(canonical_dataset_json))
            agent_logs.append(f"📎 canonical_dataset 生成成功 (len={len(canonical_dataset_json)})")
        except Exception as e:
            logger.warning("DataProfile 序列化失败", error=str(e))

    # 从 session_dir 反读 manifest.json 拿到 series_index(v4 数据契约)
    series_index_json = "(未提供)"
    if profile is not None and getattr(profile, "session_dir", None):
        try:
            catalog = SeriesCatalog.from_manifest(profile.session_dir)
            series_index_json = json.dumps(catalog.to_json(), ensure_ascii=False, indent=2)
            logger.info("series_index 注入成功", n_series=len(catalog.series))
        except Exception as e:
            logger.warning("series_index 加载失败", error=str(e))

    plan_input = {
        "data_file_path": data_file_path,
        "data_preview": data_preview,
        "canonical_dataset": canonical_dataset_json,
        "series_index": series_index_json,
        "user_chart_config": user_chart_config_json,
        "user_prompt": model_.user_prompt,
        "mcp_prompt": model_.mcp_prompt,
        "skill_prompt": skill_prompt,
    }
    plan_prompt = get_agent_chart_designer_prompt()
    plans_content = await engine.run_prompt(plan_prompt.invoke(plan_input))
    logger.debug("计划响应", plans_content=plans_content)
    logger.debug("QueryEngine 状态", engine=str(engine))

    # 保存原始计划响应，便于排查 LLM 输出格式问题
    try:
        plan_response_file = output_folder / "plan_response.txt"
        with open(plan_response_file, "w", encoding="utf-8") as f:
            f.write(plans_content or "")
    except Exception as e:
        logger.warning("保存计划响应失败", error=str(e))

    plans_data = extract_json_from_response(plans_content)

    if not plans_data:
        snippet = (plans_content or "").strip()[:500]
        raise ConfigError(f"无法解析计划数据，LLM 响应前 500 字符: {snippet}")

    try:
        plans = parse_plans(plans_data)
    except Exception as e:
        snippet = (plans_content or "").strip()[:500]
        raise ConfigError(f"计划 schema 不匹配: {e}; LLM 响应前 500 字符: {snippet}") from e

    logger.info("共找到 N 个计划", count=len(plans))

    all_plans_file = output_folder / "all_plans.json"
    with open(all_plans_file, "w", encoding="utf-8") as f:
        json.dump(plans_data, f, ensure_ascii=False, indent=2)
    logger.info("所有计划已保存", file=str(all_plans_file))

    return plans
