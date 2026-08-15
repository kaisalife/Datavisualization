"""主管线编排：数据接入 -> 计划生成 -> 并发图表生成。

本模块只负责流程编排，各阶段实现拆分至:
- data_source.py:    请求 -> DataSource 构建 + DuckDB 接入
- plan_generator.py: LLM 计划生成、解析、落盘
- chart_executor.py: 并发图表执行与结果汇总
- agent_pipeline.py: viz_mode=agent 自主流水线（替换固定 plan->generate->debug）
"""
import json
import sys
from pathlib import Path
from dotenv import load_dotenv

project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

try:
    from Entity import GenerateChartWithPromptRequest
    from service.data_preview import get_smart_file_preview
    from service.config import load_config, get_agent_class
    from service.query_engine import QueryEngine
    from service.exceptions import ConfigError
except ImportError:
    from ..Entity import GenerateChartWithPromptRequest
    from .data_preview import get_smart_file_preview
    from .config import load_config, get_agent_class
    from .query_engine import QueryEngine
    from .exceptions import ConfigError

from service.data_source import ingest_data_source
from service.plan_generator import generate_chart_plans
from service.chart_executor import execute_chart_plans, log_execution_summary
from service.monitoring import trace
from service.observability import get_logger

logger = get_logger(__name__)

load_dotenv()


def _check_cancelled(task_id):
    """检查任务是否被取消。"""
    if task_id is None:
        return False
    from api.common import is_cancelled
    return is_cancelled(task_id)


def _ensure_not_cancelled(task_id, agent_logs: list):
    if _check_cancelled(task_id):
        agent_logs.append("❌ 任务已被用户取消")
        raise RuntimeError("Task cancelled by user")


def _parse_user_chart_config(model_, agent_logs: list) -> str:
    """解析用户自定义图表配置（model_.config 为 JSON 字符串），返回注入 prompt 的 JSON 串。"""
    user_chart_config: dict = {}
    if model_.config:
        try:
            _parsed_cfg = json.loads(model_.config)
            if isinstance(_parsed_cfg, dict):
                user_chart_config = _parsed_cfg
            else:
                agent_logs.append("⚠️ 用户 config 不是 JSON 对象，已忽略")
        except Exception as e:
            logger.warning("用户 config 解析失败，忽略", error=str(e))
            agent_logs.append(f"⚠️ 用户 config 解析失败: {e}")
    return json.dumps(user_chart_config, ensure_ascii=False) if user_chart_config else "(未提供)"


async def _init_chat(model_, mcp_config, agent_logs: list):
    """创建并初始化 BaseAgent 实例。"""
    try:
        chat = get_agent_class(model_.model_type, model_.model_url, model_.model_api_key, mcp_config)
        logger.info("Chat instance created successfully")

        logger.info("正在初始化 agent")
        agent_logs.append("🔧 正在初始化 agent...")
        await chat.initialize()
        logger.info("Agent 初始化成功")
        agent_logs.append("✅ Agent 初始化成功")
        return chat
    except Exception as e:
        logger.error("创建 chat instance 失败", error=str(e), exc_info=True)
        raise ConfigError(f"Agent initialization failed: {e}") from e


def _prepare_output_folder(model_) -> tuple[Path, str]:
    """提前派生输出目录（data_preview 需要保存接口代码）。"""
    from service.constants import get_charts_dir
    base_charts_folder = get_charts_dir()
    base_charts_folder.mkdir(parents=True, exist_ok=True)
    first_file_stem = Path(model_.file_paths[0]).stem if model_.file_paths else "dataset"
    output_folder = base_charts_folder / first_file_stem
    output_folder.mkdir(exist_ok=True)
    logger.info("输出文件夹", folder=str(output_folder))
    return output_folder, first_file_stem


@trace(category="pipeline")
async def service_main(model_: GenerateChartWithPromptRequest, config_path=None, task_id=None):
    agent_logs: list[str] = []
    config = load_config(config_path)
    mcp_config = config["mcp_config"]

    user_chart_config_json = _parse_user_chart_config(model_, agent_logs)
    _ensure_not_cancelled(task_id, agent_logs)

    chat = await _init_chat(model_, mcp_config, agent_logs)

    logger.info("步骤 0: 通过 DuckDB 接入数据源")
    agent_logs.append("📄 步骤 0: 通过 DuckDB 接入数据源")

    output_folder, first_file_stem = _prepare_output_folder(model_)

    # ==== DuckDB 数据接入 ====
    engine = QueryEngine(chat_model=chat, model_name=model_.model_type)
    profile = await ingest_data_source(model_, first_file_stem, agent_logs)

    # ==== Agent 自主流水线分流（viz_mode=agent/auto 替换固定流水线）====
    if model_.viz_mode in ("agent", "auto"):
        from service.agent_pipeline import run_agent_pipeline
        agent_logs.append("🔀 进入 Agent 自主流水线")
        return await run_agent_pipeline(
            chat, model_, profile, output_folder, task_id=task_id
        )

    # ==== 旧流水线（viz_mode=legacy/chart/scientific）：data_preview + 计划 + 生成 ====
    data_test = ""
    if model_.file_paths:
        data_test, _ = await get_smart_file_preview(
            chat, model_.file_paths, output_folder=output_folder
        )
    _ensure_not_cancelled(task_id, agent_logs)

    file_test = profile.source_path  # 兼容旧字段

    # ==== 用 DataProfile 生成数据预览 (如果 data_preview 未生成) ====
    if not data_test:
        data_test = profile.to_prompt_str()
        logger.debug("数据预览 (DataProfile)", preview=data_test[:500])

    plans = await generate_chart_plans(
        engine,
        model_=model_,
        profile=profile,
        data_preview=data_test,
        data_file_path=file_test,
        output_folder=output_folder,
        user_chart_config_json=user_chart_config_json,
        agent_logs=agent_logs,
    )

    successful_charts, failed_plans = await execute_chart_plans(
        chat,
        engine,
        plans=plans,
        profile=profile,
        data_file_path=file_test,
        data_preview=data_test,
        output_folder=output_folder,
        user_config_json=user_chart_config_json,
        config=config,
        task_id=task_id,
        agent_logs=agent_logs,
    )

    _ensure_not_cancelled(task_id, agent_logs)
    log_execution_summary(successful_charts, failed_plans, agent_logs)

    return {
        "successful_charts": successful_charts,
        "failed_plans": failed_plans,
        "agent_logs": agent_logs,
    }
