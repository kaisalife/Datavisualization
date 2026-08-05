import json
import os
import sys
import asyncio
import ast
import textwrap
from pathlib import Path
from dotenv import load_dotenv

project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

try:
    from Entity import GenerateChartWithPromptRequest
    from prompts.agent_prompt import (
        get_agent_chart_designer_prompt,
        get_agent_generate_chart_prompt,
        get_agent_debug_chart_prompt
    )
    from service.data_preview import get_file_preview, get_smart_file_preview
    from service.config import load_config, get_agent_class
    from service.utils import extract_json_from_response
    from service.chart_generator import generate_single_chart
    from RAG.RAG_main import RAGRetriever
    from service.memory.project_memory import get_project_memory
    from service.query_engine import QueryEngine
    from service.exceptions import ConfigError
    from service.data_ingestion import ingest as duckdb_ingest
    from service.data_ingestion import ingest_files as duckdb_ingest_files
    from service.data_ingestion import DataSource as DuckDBSource
    from service.data_ingestion.models import DataProfile
except ImportError:
    from ..Entity import GenerateChartWithPromptRequest
    from ..prompts.agent_prompt import (
        get_agent_chart_designer_prompt,
        get_agent_generate_chart_prompt,
        get_agent_debug_chart_prompt
    )
    from .data_preview import get_file_preview, get_smart_file_preview
    from .config import load_config, get_agent_class
    from .utils import extract_json_from_response
    from .chart_generator import generate_single_chart
    from ..RAG.RAG_main import RAGRetriever
    from .memory.project_memory import get_project_memory
    from .query_engine import QueryEngine
    from .exceptions import ConfigError
    try:
        from ..data_ingestion import ingest as duckdb_ingest
        from ..data_ingestion import ingest_files as duckdb_ingest_files
        from ..data_ingestion import DataSource as DuckDBSource
        from ..data_ingestion.models import DataProfile
    except ImportError:
        duckdb_ingest = None
        duckdb_ingest_files = None
        DuckDBSource = None
        DataProfile = None

from service.monitoring import trace

load_dotenv()


def _extract_function_signatures(code_str: str) -> list:
    """从 data_preview.py 的封装代码中提取函数签名 + docstring 首行。

    data_preview.py 内部把真实代码包在 `code = '''...'''` 三引号里，先剥出。
    返回 [{"name": ..., "args": ..., "doc": ...}, ...]
    """
    # 尝试从三引号字符串里剥出真实代码
    real_code = code_str
    m_open = code_str.find("'''")
    m_close = code_str.rfind("'''")
    if m_open != -1 and m_close > m_open:
        real_code = code_str[m_open + 3:m_close]
        real_code = textwrap.dedent(real_code)

    signatures = []
    try:
        tree = ast.parse(real_code)
    except SyntaxError:
        return signatures

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            args = [a.arg for a in node.args.args]
            doc = ast.get_docstring(node) or ""
            doc_first = doc.split("\n", 1)[0].strip() if doc else ""
            signatures.append({
                "name": node.name,
                "args": args,
                "doc": doc_first,
            })
    return signatures


def _check_cancelled(task_id):
    """检查任务是否被取消"""
    if task_id is None:
        return False
    from api.common import is_cancelled
    return is_cancelled(task_id)


@trace(category="pipeline")
async def service_main(model_: GenerateChartWithPromptRequest, config_path=None, task_id=None):
    agent_logs: list[str] = []
    config = load_config(config_path)
    mcp_config = config["mcp_config"]

    # 解析用户自定义图表配置（model_.config 为 JSON 字符串，与系统 config 不同）
    user_chart_config: dict = {}
    if model_.config:
        try:
            _parsed_cfg = json.loads(model_.config)
            if isinstance(_parsed_cfg, dict):
                user_chart_config = _parsed_cfg
            else:
                agent_logs.append("⚠️ 用户 config 不是 JSON 对象，已忽略")
        except Exception as e:
            print(f"⚠️ 用户 config 解析失败，忽略: {e}")
            agent_logs.append(f"⚠️ 用户 config 解析失败: {e}")
    user_chart_config_json = json.dumps(user_chart_config, ensure_ascii=False) if user_chart_config else "(未提供)"

    if _check_cancelled(task_id):
        agent_logs.append("❌ 任务已被用户取消")
        raise RuntimeError("Task cancelled by user")

    try:
        chat = get_agent_class(model_.model_type, model_.model_url, model_.model_api_key, mcp_config)
        print("✅ Chat instance created successfully")

        print("\n🔧 正在初始化 agent...")
        agent_logs.append("🔧 正在初始化 agent...")
        await chat.initialize()
        print("✅ Agent 初始化成功")
        agent_logs.append("✅ Agent 初始化成功")
    except Exception as e:
        print(f"❌ Error: {e}, while creating chat instance: {model_.model_type}, {model_.model_url}")
        raise ConfigError(f"Agent initialization failed: {e}") from e

    print("\n" + "="*60)
    print("📄 步骤 0: 通过 DuckDB 接入数据源")
    print("="*60)
    agent_logs.append("📄 步骤 0: 通过 DuckDB 接入数据源")

    plan_prompt = get_agent_chart_designer_prompt()

    # ==== 提前派生输出目录（data_preview 需要保存接口代码）====
    base_charts_folder = Path("./charts")
    base_charts_folder.mkdir(exist_ok=True)
    first_file_stem = Path(model_.file_paths[0]).stem if model_.file_paths else "dataset"
    output_folder = base_charts_folder / first_file_stem
    output_folder.mkdir(exist_ok=True)
    print(f"\n📁 输出文件夹: {output_folder}")

    # ==== DuckDB 数据接入 ====
    if duckdb_ingest is None:
        raise ConfigError("data_ingestion 模块未安装，请检查依赖")

    # 构造 DataSource 并接入
    engine = QueryEngine(chat_model=chat, model_name=model_.model_type)

    try:
        if model_.file_paths:
            if len(model_.file_paths) > 1:
                # 多文件: 全部接入同一个 DuckDB 会话
                profile = await duckdb_ingest_files(model_.file_paths)
            else:
                # 单文件
                source = DuckDBSource(kind="file", path=model_.file_paths[0], name=first_file_stem)
                profile = await duckdb_ingest(source)
        elif model_.db_config:
            # 数据库源
            db_type = model_.db_config.get("type", "postgresql")
            source = DuckDBSource(
                kind="database",
                db_type=db_type,
                db_config=model_.db_config,
                options={"tables": model_.db_config.get("tables"), "query": model_.db_config.get("query")},
            )
            profile = await duckdb_ingest(source)
        else:
            raise ConfigError("必须提供文件或数据库配置")
    except Exception as e:
        raise ConfigError(f"DuckDB 数据接入失败: {e}") from e

    print(f"✅ 数据接入成功: 表名={profile.table_name}, 行数={profile.row_count}")
    print(f"   DuckDB 路径: {profile.duckdb_path}")
    print(f"   Schema: {[(c['name'], c['type']) for c in profile.schema]}")
    agent_logs.append(f"✅ 数据接入成功: {profile.table_name} ({profile.row_count} 行)")

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

    if _check_cancelled(task_id):
        agent_logs.append("❌ 任务已被用户取消")
        raise RuntimeError("Task cancelled by user")

    # DuckDB 路径和表名传给 chart_generator
    file_test = profile.source_path  # 兼容旧字段
    duckdb_path = profile.duckdb_path
    table_name = profile.table_name

    # ==== 用 DataProfile 生成数据预览 (如果 data_preview 未生成) ====
    if not data_test:
        data_test = profile.to_prompt_str()
        print(f"📎 数据预览 (DataProfile):\n{data_test[:500]}...")

    data_interface_info = ""
    
    print("\n" + "="*60)
    print("📋 步骤 1: 生成图表计划")
    print("="*60)
    agent_logs.append("📋 步骤 1: 生成图表计划")

    project_memory = get_project_memory()
    skill_prompt = (project_memory + "\n" + model_.skill_prompt) if project_memory else model_.skill_prompt

    # DataProfile 通过 canonical_dataset 注入 planner
    canonical_dataset_json = "(未提供)"
    if profile is not None:
        try:
            import json as _json
            canonical_dataset_json = _json.dumps(profile.to_prompt_dict(), ensure_ascii=False, indent=2)
            print(f"📎 canonical_dataset 生成成功 (len={len(canonical_dataset_json)})")
            agent_logs.append(f"📎 canonical_dataset 生成成功 (len={len(canonical_dataset_json)})")
        except Exception as e:
            print(f"⚠️ DataProfile 序列化失败: {e}")

    plan_input = {
        "data_file_path": file_test,
        "data_preview": data_test,
        "data_interface_info": data_interface_info,
        "canonical_dataset": canonical_dataset_json,
        "user_chart_config": user_chart_config_json,
        "user_prompt": model_.user_prompt,
        "mcp_prompt": model_.mcp_prompt,
        "skill_prompt": skill_prompt
    }
    plans_content = await engine.run_prompt(plan_prompt.invoke(plan_input))
    print(f"\n📝 计划响应:\n{plans_content}")
    print(f"\n🔧 QueryEngine 状态: {engine}")

    # 保存原始计划响应，便于排查 LLM 输出格式问题
    try:
        plan_response_file = output_folder / "plan_response.txt"
        with open(plan_response_file, "w", encoding="utf-8") as f:
            f.write(plans_content or "")
    except Exception as e:
        print(f"⚠️ 保存计划响应失败: {e}")

    plans_data = extract_json_from_response(plans_content)

    # 兼容 LLM 直接返回 plans 数组的情况
    if isinstance(plans_data, list):
        plans_data = {"plans": plans_data}

    if not plans_data or "plans" not in plans_data:
        snippet = (plans_content or "").strip()[:500]
        raise ConfigError(f"无法解析计划数据，LLM 响应前 500 字符: {snippet}")

    plans = plans_data.get("plans", [])
    print(f"\n📊 共找到 {len(plans)} 个计划")

    # output_folder 已在步骤 0 阶段基于源类型创建，这里不再重建
    print(f"\n📁 输出文件夹: {output_folder}")

    all_plans_file = output_folder / "all_plans.json"
    with open(all_plans_file, "w", encoding="utf-8") as f:
        json.dump(plans_data, f, ensure_ascii=False, indent=2)
    print(f"💾 所有计划已保存: {all_plans_file}")

    if _check_cancelled(task_id):
        agent_logs.append("❌ 任务已被用户取消")
        raise RuntimeError("Task cancelled by user")

    print("\n🔗 初始化生成和调试提示...")
    generate_prompt = get_agent_generate_chart_prompt()
    debug_prompt = get_agent_debug_chart_prompt()
    print("✅ 提示初始化完成")
    
    print("\n🔍 初始化 RAG 检索器...")
    try:
        rag_retriever = RAGRetriever()
        print("✅ RAG 检索器初始化成功")
    except Exception as e:
        print(f"⚠️ RAG 检索器初始化失败: {e}")
        rag_retriever = None
    
    successful_charts = []
    failed_plans = []

    # 生成简化的 dataset_summary（列 schema），供 chart_generator 每个 chart 复用
    dataset_summary_json = "(未提供)"
    if profile is not None:
        try:
            dataset_summary_json = json.dumps({
                "source_kind": profile.source_kind,
                "table_name": profile.table_name,
                "columns": profile.schema,
                "row_count": profile.row_count,
            }, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ dataset_summary 生成失败: {e}")

    try:
        ordered_plans = sorted(plans, key=lambda x: x.get("execution_order", 0))

        # 并发度 & 重试次数：优先读取 config.chart_generation，其次读环境变量，最后使用默认
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
        semaphore = asyncio.Semaphore(concurrency)
        print(f"🚀 plans 并发度: {concurrency}, max_retries: {max_retries}")
        agent_logs.append(f"🚀 plans 并发度: {concurrency}, max_retries: {max_retries}")

        if _check_cancelled(task_id):
            agent_logs.append("❌ 任务已被用户取消")
            raise RuntimeError("Task cancelled by user")

        async def _run_one(plan_item: dict):
            async with semaphore:
                if engine.aborted:
                    print("⚠️ QueryEngine 已中止，跳过 plan")
                    return plan_item, False, "", "aborted"
                success, chart_path, error = await generate_single_chart(
                    chat=chat,
                    plan=plan_item,
                    data_file_path=file_test,
                    data_preview=data_test,
                    output_folder=output_folder,
                    engine=engine,
                    generate_prompt=generate_prompt,
                    debug_prompt=debug_prompt,
                    retriever=rag_retriever,
                    max_retries=max_retries,
                    dataset_summary=dataset_summary_json,
                    duckdb_path=duckdb_path,
                    table_name=table_name,
                    user_config=user_chart_config_json,
                )
                return plan_item, success, chart_path, error

        results = await asyncio.gather(
            *(_run_one(p) for p in ordered_plans),
            return_exceptions=True,
        )

        for res in results:
            if isinstance(res, Exception):
                failed_plans.append({"plan": {}, "error": f"gather 异常: {res}"})
                continue
            plan_item, success, chart_path, error = res
            if success and chart_path:
                successful_charts.append({
                    "plan": plan_item,
                    "chart_path": chart_path,
                })
            else:
                failed_plans.append({
                    "plan": plan_item,
                    "error": error,
                })
    finally:
        # DuckDB 文件在 profile.duckdb_path，可按需清理
        pass
    
    if _check_cancelled(task_id):
        agent_logs.append("❌ 任务已被用户取消")
        raise RuntimeError("Task cancelled by user")

    print("\n" + "="*60)
    print("📊 执行总结")
    print("="*60)
    print(f"✅ 成功: {len(successful_charts)} 个图表")
    print(f"❌ 失败: {len(failed_plans)} 个计划")
    agent_logs.append("📊 执行总结")
    agent_logs.append(f"✅ 成功: {len(successful_charts)} 个图表")
    agent_logs.append(f"❌ 失败: {len(failed_plans)} 个计划")
    
    if successful_charts:
        print("\n📁 成功的图表:")
        for idx, item in enumerate(successful_charts, 1):
            print(f"  {idx}. {item['plan']['plan_name']} -> {item['chart_path']}")
        for idx, item in enumerate(successful_charts, 1):
            agent_logs.append(f"  📁 图表 {idx}: {item['plan']['plan_name']} -> {item['chart_path']}")
    
    if failed_plans:
        print("\n❌ 失败的计划:")
        for idx, item in enumerate(failed_plans, 1):
            print(f"  {idx}. {item['plan']['plan_name']}: {item['error'][:100]}...")
        for idx, item in enumerate(failed_plans, 1):
            plan_name = item['plan'].get('plan_name', 'unknown') if item['plan'] else 'unknown'
            agent_logs.append(f"  ❌ 计划 {idx}: {plan_name} 失败: {item['error'][:100]}")
    
    return {
        "successful_charts": successful_charts,
        "failed_plans": failed_plans,
        "agent_logs": agent_logs,
    }
