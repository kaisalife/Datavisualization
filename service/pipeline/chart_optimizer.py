"""单图二次优化：用户挑一张已生成的图，agent 基于优化指令改代码重新渲染。

与 debug 循环的区别：

- debug 修的是「执行失败」的代码（目标是恢复计划要求）；
- 优化改的是「执行成功」的代码（目标是用户新指令：改标题/配色/Top-N/阈值…），
  十个像素都不许丢的是**数据契约**：series 读取代码仍由守护层注入，
  变换与绘图才是优化对象。

知识库：pyecharts API 参考走 RAG（``retrieve_reference_docs``，与生成阶段
同一检索器），数据证据走 ``read_series_sample`` / ``run_code`` 沙箱试跑。
产物与首次生成完全同构：同样的注入版自包含代码、同样的 HTML 校验与
数据检查；原图永不覆盖（新文件名），并登记进资产清单。
"""
from __future__ import annotations

import json
from pathlib import Path

from service.observability import get_logger
from service.pipeline import generation_validation as gv
from service.pipeline.chart_debugger import (
    SeriesRunCodeTool,
    debug_with_agent,
)
from service.pipeline.chart_rag import retrieve_reference_docs
from service.pipeline.chart_sandbox import _RENDER_HEADER, SandboxResult, execute_chart_code

try:
    from Entity.plan_models import plan_get
except ImportError:
    from ..plan_models import plan_get  # type: ignore  # pragma: no cover

logger = get_logger(__name__)

# 优化默认轮数：比生成少——优化是在成功产物上做增量，通常 1 轮内完成
OPTIMIZE_MAX_ATTEMPTS = 3


def _build_optimize_message(
    *, user_prompt: str, original_code: str, chart_id: str,
    plan_details: str, dataset_summary: str, series_hint: str,
    reference_docs: str, error: str = "",
) -> str:
    """构建优化 agent 初始消息（产物契约 + 优化指令 + 证据）。"""
    error_section = (
        f"\n\n## 上一轮失败的真实报错（必须修复）\n{error}" if error.strip() else ""
    )
    return f"""基于下面的已成功图表代码，按用户的优化指令改出新的完整代码。
你有两个工具可用：
- run_code: 在沙箱中试跑代码（series 读取代码会自动拼在你的代码开头，df 已就绪）
- read_series_sample: 只读查看真实数据（列名/取值/分布），不要猜数据形状

## 优化要求
1. 先读懂原代码，只改优化指令涉及的部分；指令没说的行为保持原样
2. 读取代码已由守护层在开头提供（df 已从 series 加载），
   禁止 import duckdb / read_parquet 重新加载 / 重新定义 df
3. 优化后用 run_code 验证通过（HTML 正常渲染、数据检查无错误）
4. 最终回答**仅返回修改后的完整 Python 代码**（代码块包裹，无其他文字）

## 用户优化指令（本次目标，优先级最高）
{user_prompt}

## 原始图表（{chart_id}）
{plan_details}

## 可参考的 pyecharts API 示例（可能为空）
{reference_docs or "(无)"}

## 数据列 schema
{dataset_summary}

## 数据契约
{series_hint}

## 原始成功代码
```python
{original_code}
```{error_section}"""


def _read_code_from_data_path(data_path: str) -> str:
    """按数据契约生成 series 读取片段（优化产物与首次生成同构）。"""
    if not data_path:
        return ""
    from service.data_ingestion.series.models import SemanticSeries
    from service.data_ingestion.series.snippet import series_snippet

    return series_snippet(_synthesize_series(data_path))


def _synthesize_series(data_path: str) -> "SemanticSeries":
    """从 series .parquet 绝对路径合成最小可用的 SemanticSeries。"""
    from service.data_ingestion.series.models import SemanticSeries

    stem = Path(data_path).stem
    return SemanticSeries(
        series_id=stem,
        name=stem,
        axis_kind="generic",
        row_label_column=None,
        column_label_columns=[],
        data_path=str(Path(data_path)),
        source_table="optimize",
    )


async def optimize_single_chart(
    chat,
    *,
    user_prompt: str,
    plan: dict,
    original_code: str,
    chart_id: str,
    data_path: str,
    output_folder: Path,
    engine=None,
    retriever=None,
    dataset_summary: str = "(未提供)",
    max_attempts: int = OPTIMIZE_MAX_ATTEMPTS,
) -> tuple[bool, str, str, str, str]:
    """优化单张图：agent 工具循环改代码 → 沙箱执行 → 产物校验。

    Args:
        chat: 已初始化 BaseAgent（须有 arun_with_tools）
        user_prompt: 用户的优化指令
        plan: 原始 plan dict（详情进 prompt；不修改其校验字段）
        original_code: 原始成功代码（注入版，来自 code/assets.json 登记）
        chart_id: 被优化的 HTML 文件名（仅用于消息引用）
        data_path: series .parquet 绝对路径（自备读取模式为空）
        output_folder: 原图所在输出目录（优化产物落同一目录）
        engine: QueryEngine（可 None；优化只用 chat 工具循环）
        retriever: RAG 检索器（None 则不检索）
        dataset_summary: 数据 schema 描述
        max_attempts: 最多尝试次数（每轮失败把真实报错回喂 agent）

    Returns:
        (成功与否, chart_path, 最终代码（不含注入段）, 新 plan_id, 错误信息)
    """
    plans_folder = output_folder / "plans"
    code_folder = output_folder / "code"
    charts_folder = output_folder / "charts"
    for folder in (plans_folder, code_folder, charts_folder):
        folder.mkdir(parents=True, exist_ok=True)

    plan_details = json.dumps(plan, ensure_ascii=False, indent=2)
    series_hint = (
        "读取代码已由守护层完成（变量 df=已从 series 加载）。\n"
        "【硬性约束】禁止 import duckdb、禁止 read_parquet 重新加载、禁止重新定义 df，"
        "直接在 df 上做数据变换与绘图。"
    )
    reference_docs = retrieve_reference_docs(retriever, plan) or ""
    read_code = _read_code_from_data_path(data_path)
    loop_id = plan_get(plan, "plan_id", "unknown")
    final_code = ""
    last_error = ""
    version = 0
    plan_id = ""

    for attempt in range(1, max_attempts + 1):
        message = _build_optimize_message(
            user_prompt=user_prompt,
            original_code=original_code,
            chart_id=chart_id,
            plan_details=plan_details,
            dataset_summary=dataset_summary,
            series_hint=series_hint,
            reference_docs=reference_docs,
            error=last_error,
        )
        code, logs = await debug_with_agent(
            chat, tools=_build_tools(output_folder, data_path), message=message
        )
        for line in logs:
            logger.info("优化 agent", log=line)
        final_code = code
        if not final_code.strip():
            last_error = "优化 agent 未返回有效代码"
            continue

        # 优化产物命名：<原 plan_id>_opt<N>——原图/原代码永不覆盖
        version += 1
        plan_id = f"{loop_id}_opt{version}"
        body = (read_code + "\n" + final_code) if read_code else final_code
        result = execute_chart_code(body, charts_folder=charts_folder, plan_id=plan_id)
        report = gv.runtime_report(
            ok=result.success, attempt=attempt,
            chart_path=result.chart_path,
            data_stats=getattr(result, "data_stats", None),
            chart_type=plan_get(plan, "chart_type", ""),
        )
        if result.success and report["ok"]:
            _save_code(code_folder, plan_id, "success", body)
            logger.info(
                "图表优化成功", origin=chart_id, plan_id=plan_id,
                chart_path=result.chart_path,
            )
            return True, str(result.chart_path), final_code, plan_id, ""
        last_error = (
            gv.format_report_errors(report) if result.success else result.output
        )
        logger.warning(
            "优化后执行未通过", attempt=attempt, plan_id=plan_id, error=last_error[:200]
        )
        try:
            _save_code(code_folder, plan_id, "failed", final_code)
        except Exception:
            pass
        # 静态安全拒绝（AST 规则）不可由 agent 修复，直接终止
        if not result.success and "安全检查失败" in last_error:
            break
    return False, "", final_code, "", last_error or "优化未成功"


def _save_code(code_folder: Path, plan_id: str, suffix: str, code: str) -> Path:
    """优化代码落盘（契约与首次生成一致：code_<plan_id>_<suffix>.py）。"""
    code_file = code_folder / f"code_{plan_id}_{suffix}.py"
    code_file.write_text(code, encoding="utf-8")
    return code_file


def _build_tools(output_folder: Path, data_path: str) -> list:
    """优化工具池：与 debug 一致（run_code 试跑 + read_series_sample 只读证据）。"""
    from agent.tools.base import ToolContext
    from agent.tools.read_table_sample_tool import ReadSeriesSampleTool
    from agent.tool_adapter import wrap_local_tools
    from service.data_ingestion.series.models import SeriesCatalog

    read_code = _read_code_from_data_path(data_path)
    local_tools = [
        SeriesRunCodeTool(
            read_code=read_code,
            auto_confirm=True,
            output_dir=str(output_folder / "charts"),
            prelude=_RENDER_HEADER,
        ),
    ]
    if data_path:
        catalog = SeriesCatalog(
            datasets_dir=str(Path(data_path).parent),
            series=[_synthesize_series(data_path)],
        )
        local_tools.append(ReadSeriesSampleTool(catalog=catalog))
    ctx = ToolContext(auto_confirm=True, working_dir=str(output_folder))
    return wrap_local_tools(local_tools, ctx)
