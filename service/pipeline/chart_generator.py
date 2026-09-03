"""图表生成编排（v4 series 化，沙箱执行已拆至 chart_sandbox.py，RAG 检索拆至 chart_rag.py）。

流程（每 plan）：
1. 解析 series（plan.series_id -> 目录），运行时加载得到 df 预览
2. LLM 只看数据契约（df schema + 样本行），只写变换与绘图代码
3. 守护层拼接 read_code（从 series .parquet 加载 df）+ LLM 代码 -> 沙箱执行 -> 产物校验
4. 失败回喂 debug 重试；产物落盘（注入版自包含代码）
"""
from __future__ import annotations

import json
from pathlib import Path

from agent import BaseAgent
from service.data_ingestion.series import load_series_df, series_snippet
from service.data_ingestion.series.models import SeriesCatalog
from service.monitoring import trace
from service.observability import get_logger
from service.pipeline.chart_rag import retrieve_reference_docs
from service.pipeline.chart_sandbox import _RENDER_HEADER, execute_chart_code  # noqa: F401  向后兼容旧 import
from service.runtime.utils import extract_code_from_response

try:
    from Entity.plan_models import plan_get
except ImportError:
    from ..plan_models import plan_get

logger = get_logger(__name__)


def _build_series_hint(series_id: str, df_preview: str = "") -> str:
    """构建注入 prompt 的数据契约（df 已就绪，禁止自己读数据）。"""
    if not series_id:
        return "(无)"
    hint = (
        f"读取代码已由守护层完成（变量 df=已从 series {series_id} 加载）。\n"
        "【硬性约束】禁止 import duckdb、禁止 read_parquet 重新加载、禁止重新定义 df，"
        "直接在 df 上做数据变换与绘图。"
    )
    if df_preview:
        hint += f"\n\ndf 真实预览（前几行，直接用）:\n{df_preview}"
    return hint


async def _invoke_llm(engine, chat: BaseAgent, prompt, input_data: dict) -> str:
    """统一 LLM 调用：QueryEngine 优先 -> prompt+chat -> 裸 chat（兜底）。

    prompt 缺失（测试/兜底路径）时把输入 dict 渲染成可读文本，
    包成 {"user_prompt": ...}（BaseAgent.ainvoke 只认 ChatPromptValue 或含 user_prompt 的 dict）。
    """
    if engine is not None and prompt is not None:
        return await engine.run_prompt(prompt.invoke(input_data))
    if prompt is not None:
        payload: object = prompt.invoke(input_data)
    else:
        rendered = "\n".join(f"{k}: {v}" for k, v in input_data.items())
        payload = {"user_prompt": rendered}
    response = await chat.ainvoke(payload)
    return response["content"] if isinstance(response, dict) else str(response)


def _save_code(code_folder: Path, plan_id: str, suffix: str, code: str) -> None:
    """落盘代码文件（success/failed/rejected 命名契约）。"""
    code_file = code_folder / f"code_{plan_id}_{suffix}.py"
    with open(code_file, "w", encoding="utf-8") as f:
        f.write(code)
    logger.info("代码已保存", code_file=str(code_file), suffix=suffix)


@trace(category="chart_gen")
async def generate_single_chart(
    chat: BaseAgent,
    plan: dict,
    data_file_path: str,
    data_preview: str,
    output_folder: Path,
    engine=None,
    generate_prompt=None,
    debug_prompt=None,
    generate_chain=None,
    debug_chain=None,
    retriever=None,
    max_retries: int = 3,
    dataset_summary: str = "",
    user_config: str = "(未提供)",
    catalog: "SeriesCatalog | None" = None,
) -> tuple[bool, str, str, str]:
    """生成并执行单个图表计划（v4）。

    Args:
        catalog: 语义 series 目录（plan.series_id 解析为 df 加载）

    Returns:
        (成功与否, chart_path, 最终代码, 错误信息)
    """
    plan_id = plan_get(plan, "plan_id", "unknown")
    plan_name = plan_get(plan, "plan_name", "Unknown Plan")
    logger.info("开始执行计划", plan_id=plan_id, plan_name=plan_name)

    plans_folder = output_folder / "plans"
    code_folder = output_folder / "code"
    charts_folder = output_folder / "charts"
    for folder in (plans_folder, code_folder, charts_folder):
        folder.mkdir(exist_ok=True)
    with open(plans_folder / f"plan_{plan_id}.json", "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)

    plan_details = json.dumps(plan, ensure_ascii=False, indent=2)
    # 读取代码只从 series 目录物化（单一真相），不取 plan.read_code——plan_details 不进读取代码
    series_id = plan_get(plan, "series_id", "")
    series = catalog.by_id(series_id) if catalog is not None and series_id else None
    read_code = series_snippet(series) if series is not None else ""
    # 数据契约：真实加载 series 给出 df 预览，LLM 信任 df 直接绘图
    df_preview = ""
    if series is not None:
        try:
            df_preview = load_series_df(series).head(5).to_string(max_colwidth=30)
        except Exception as e:
            logger.warning("series 预览失败", series_id=series_id, error=str(e))
    series_hint = _build_series_hint(series_id, df_preview)
    reference_docs = retrieve_reference_docs(retriever, plan)

    final_code = ""
    code = ""
    last_error = ""

    for attempt in range(max_retries):
        if engine and engine.aborted:
            logger.warning("QueryEngine 已中止，停止生成")
            break

        if attempt == 0:
            content = await _invoke_llm(engine, chat, generate_prompt, {
                "data_file_path": data_file_path,
                "data_preview": data_preview,
                "plan_details": plan_details,
                "reference_docs": reference_docs,
                "dataset_summary": dataset_summary or "(未提供)",
                "user_config": user_config,
                "read_recipe_hint": series_hint,
            })
            code = extract_code_from_response(content)
        else:
            # debug：agent 工具循环优先（真实报错 + 真实数据），prompt 重试兜底
            from service.pipeline.chart_debugger import debug_code
            code = await debug_code(
                chat,
                engine=engine,
                debug_prompt=debug_prompt,
                plan_details=plan_details,
                code=code,
                last_error=last_error,
                dataset_summary=dataset_summary or "(未提供)",
                read_recipe_hint=series_hint,
                output_folder=output_folder,
                catalog=catalog,
                read_code=read_code,
            )
        final_code = code

        if not final_code.strip():
            last_error = "LLM 未返回有效代码（提取到空代码块）"
            logger.warning("代码为空，跳过执行", attempt=attempt + 1)
            if attempt >= max_retries - 1:
                _save_code(code_folder, plan_id, "failed", final_code)
            continue

        # 守护层拼接：read_code（真实 series 加载代码）+ LLM 代码（变换+绘图）
        body = (read_code + "\n" + code) if read_code else code

        result = execute_chart_code(
            body,
            charts_folder=charts_folder,
            plan_id=plan_id,
        )

        if result.success:
            # 产物落盘：注入版自包含代码（拷走 py + 对应 series .parquet 即可独立运行）
            _save_code(code_folder, plan_id, "success", body)
            logger.info("计划执行成功", plan_id=plan_id, chart_path=result.chart_path)
            return True, result.chart_path, body, ""

        last_error = result.output
        logger.error("执行失败", error=last_error)

        # 沙箱静态拒绝（AST 安全检查）不适合走 debug，debug 也改不了规则
        if "安全检查失败" in last_error:
            _save_code(code_folder, plan_id, "rejected", final_code)
            break
        if attempt >= max_retries - 1:
            _save_code(code_folder, plan_id, "failed", final_code)

    return False, "", final_code, last_error