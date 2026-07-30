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
    from service.viz_data import VizDataset
    from service.viz_data.factory import create_adapter
    from service.viz_data.adapters.base import AdapterError
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
    from .viz_data import VizDataset
    from .viz_data.factory import create_adapter
    from .viz_data.adapters.base import AdapterError

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


async def service_main(model_: GenerateChartWithPromptRequest, config_path=None, task_id=None):
    agent_logs: list[str] = []
    config = load_config(config_path)
    mcp_config = config["mcp_config"]

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
    print("📄 步骤 0: 通过 Adapter 层生成 VizDataset")
    print("="*60)
    agent_logs.append("📄 步骤 0: 通过 Adapter 层生成 VizDataset")

    plan_prompt = get_agent_chart_designer_prompt()

    # ==== 构造 Adapter（新路径唯一入口）====
    try:
        adapter = create_adapter(model_)
    except AdapterError as e:
        raise ConfigError(f"无法匹配数据源 Adapter: {e}") from e

    # 提前初始化 QueryEngine（DatabaseAdapter 生成 SQL 时需要）
    engine = QueryEngine(chat_model=chat, model_name=model_.model_type)

    # 根据 Adapter 能力决定是否注入 engine
    needs_llm = adapter.capabilities().needs_llm
    print(f"🔀 Adapter={type(adapter).__name__} source={adapter.source_kind()} needs_llm={needs_llm}")
    agent_logs.append(f"🔀 Adapter={type(adapter).__name__} source={adapter.source_kind()} needs_llm={needs_llm}")

    try:
        dataset = await adapter.adapt(engine=engine if needs_llm else None)
    except AdapterError as e:
        raise ConfigError(f"Adapter 失败: {e}") from e

    print(f"✅ VizDataset 生成成功: {dataset.name} (id={dataset.dataset_id})")
    print(f"   primary_form={dataset.primary_form}, "
          f"tabular_rows={dataset.tabular.row_count if dataset.tabular else 0}")

    if _check_cancelled(task_id):
        agent_logs.append("❌ 任务已被用户取消")
        raise RuntimeError("Task cancelled by user")

    # ==== 派生输出目录 & 主数据路径 ====
    data_file_name = dataset.logical_id()
    base_charts_folder = Path("./charts")
    base_charts_folder.mkdir(exist_ok=True)
    output_folder = base_charts_folder / data_file_name
    output_folder.mkdir(exist_ok=True)
    print(f"\n📁 输出文件夹: {output_folder}")

    # 主数据文件路径：优先用 VizDataset 落盘的 parquet；
    # 文件源在多文件场景可能与 primary_data_path 不同，兼容处理。
    file_test = dataset.primary_data_path() or (
        model_.file_paths[0] if model_.file_paths else ""
    )

    # ==== 派生数据预览 & 接口代码 ====
    # 文件源保留 get_smart_file_preview（会生成 data_interface_codes 供 LLM 用）
    if dataset.source_kind == "file" and model_.file_paths:
        data_test, data_interface_codes = await get_smart_file_preview(
            chat, model_.file_paths, output_folder=output_folder
        )
    else:
        data_test = adapter.preview_text(dataset)
        data_interface_codes = []
        if file_test:
            print(f"📎 主数据文件: {file_test}")

    data_interface_info = ""
    if data_interface_codes:
        # 只传函数签名摘要，避免完整代码 (~4KB/file) 反复塞进 prompt
        summarized = [
            {
                "file_path": item["file_path"],
                "code_file": item["code_file"],
                "functions": _extract_function_signatures(item["code"]),
            }
            for item in data_interface_codes
        ]
        data_interface_info = json.dumps(summarized, ensure_ascii=False, indent=2)
        print(f"\n📊 数据接口信息（摘要 {len(data_interface_info)} 字符）:\n{data_interface_info}")
    
    print("\n" + "="*60)
    print("📋 步骤 1: 生成图表计划")
    print("="*60)
    agent_logs.append("📋 步骤 1: 生成图表计划")

    project_memory = get_project_memory()
    skill_prompt = (project_memory + "\n" + model_.skill_prompt) if project_memory else model_.skill_prompt

    # Adapter 生成的 VizDataset 通过独立字段 canonical_dataset 注入 planner
    canonical_dataset_json = "(未提供)"
    if dataset is not None:
        try:
            canonical_dataset_json = dataset.to_prompt_json()
            print(f"📎 canonical_dataset 生成成功 (len={len(canonical_dataset_json)})")
            agent_logs.append(f"📎 canonical_dataset 生成成功 (len={len(canonical_dataset_json)})")
        except Exception as e:
            print(f"⚠️ VizDataset 序列化失败: {e}")

    plan_input = {
        "data_file_path": file_test,
        "data_preview": data_test,
        "data_interface_info": data_interface_info,
        "canonical_dataset": canonical_dataset_json,
        "user_prompt": model_.user_prompt,
        "mcp_prompt": model_.mcp_prompt,
        "skill_prompt": skill_prompt
    }
    plans_content = await engine.run_prompt(plan_prompt.invoke(plan_input))
    print(f"\n📝 计划响应:\n{plans_content}")
    print(f"\n🔧 QueryEngine 状态: {engine}")
    
    plans_data = extract_json_from_response(plans_content)
    
    if not plans_data or "plans" not in plans_data:
        print("❌ 无法解析计划数据")
        return
    
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
    if dataset is not None and dataset.tabular is not None:
        try:
            dataset_summary_json = json.dumps({
                "source_kind": dataset.source_kind,
                "primary_form": dataset.primary_form,
                "columns": [c.to_dict() for c in dataset.tabular.columns],
                "row_count": dataset.tabular.row_count,
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
        # 清理 VizDataset 临时目录
        if dataset is not None:
            try:
                dataset.cleanup()
            except Exception as e:
                print(f"⚠️ VizDataset 清理失败: {e}")
    
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
