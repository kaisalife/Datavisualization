"""图表 debug 层：agent 工具循环修代码（v4）。

主路径：chat.arun_with_tools + 工具池（run_code 试跑拿真实报错、
read_series_sample 看真实数据），上限 max_rounds 轮，基于真实证据修复。
fallback：agent 不可用（异常/无工具能力）时退回原 prompt 重试。

SeriesRunCodeTool：series 模式下试跑前把真实读取代码拼在开头，
与守护层拼接行为一致，保证报错即真实报错（读取代码不进 LLM 上下文）。
"""
from __future__ import annotations

from pathlib import Path

from agent.tools.base import ToolContext
from agent.tools.read_table_sample_tool import ReadSeriesSampleTool
from agent.tools.run_code_tool import RunCodeTool
from agent.tool_adapter import wrap_local_tools
from service.observability import get_logger
from service.pipeline.chart_sandbox import _RENDER_HEADER
from service.runtime.utils import extract_code_from_response

logger = get_logger(__name__)

DEBUG_MAX_ROUNDS = 5


class SeriesRunCodeTool(RunCodeTool):
    """debug 用 RunCodeTool：试跑前把 read_code（真实 series 读取代码）拼在开头。"""

    def __init__(self, read_code: str, **kwargs):
        super().__init__(**kwargs)
        self._read_code = read_code

    async def call(self, input_data: dict, ctx: ToolContext):
        code = str(input_data.get("code", ""))
        if self._read_code:
            input_data = {**input_data, "code": self._read_code + "\n" + code}
        return await super().call(input_data, ctx)


def _build_debug_tools(
    output_folder: Path, charts_folder: Path, catalog, read_code: str,
) -> list:
    """构建 debug 工具池（run_code + read_series_sample，langchain 包装）。"""
    local_tools = [
        SeriesRunCodeTool(
            read_code=read_code,
            auto_confirm=True,
            output_dir=str(charts_folder),
            prelude=_RENDER_HEADER,
        ),
        ReadSeriesSampleTool(catalog=catalog),
    ]
    ctx = ToolContext(auto_confirm=True, working_dir=str(output_folder))
    return wrap_local_tools(local_tools, ctx)


def _build_debug_message(
    *, plan_details: str, failed_code: str, error: str,
    dataset_summary: str, read_recipe_hint: str,
) -> str:
    """构建 debug agent 初始消息（任务 + 证据 + 工具说明 + 输出契约）。"""
    return f"""修复下面这段图表生成代码。你有两个工具可用：
- run_code: 在沙箱中试跑代码，拿到真实报错/输出（series 模式下读取代码会自动拼在你的代码开头）
- read_series_sample: 只读查看某个语义 series 的真实数据（列名/取值/分布）

## 修复要求
1. 先用 run_code 复现错误（或直接读报错分析），必要时用 read_series_sample 确认列名与数据
2. 修复后用 run_code 验证通过（生成 HTML 无报错）
3. 保持计划要求（chart_type/chart_title/数据列）
4. 读取代码已由守护层在代码开头提供（df 已从 series 加载），禁止 import duckdb / read_parquet 重新加载 / 重新定义 df，只修变换与绘图部分
5. 最终回答**仅返回修复后的完整 Python 代码**（代码块包裹，无其他文字）

## 计划
{plan_details}

## 失败代码
```python
{failed_code}
```

## 真实报错
{error}

## 数据列 schema
{dataset_summary}

## read_recipe_hint
{read_recipe_hint}"""


async def debug_with_agent(
    chat, *, tools: list, message: str, max_rounds: int = DEBUG_MAX_ROUNDS,
) -> tuple[str, list[str]]:
    """agent 工具循环 debug。

    Args:
        chat: 已初始化 BaseAgent（须有 arun_with_tools）
        tools: debug 工具池（langchain BaseTool 列表）
        message: 初始消息（_build_debug_message 产物）
        max_rounds: 最大工具调用轮次

    Returns:
        (修复后代码（可能为空）, agent 日志列表)
    """
    result = await chat.arun_with_tools(message, max_iterations=max_rounds, tools=tools)
    content = result.get("content", "") if isinstance(result, dict) else str(result)
    logs = result.get("agent_logs", []) if isinstance(result, dict) else []
    code = extract_code_from_response(content)
    if not code.strip():
        logs.append("⚠️ debug agent 未返回有效代码")
    return code, logs


async def debug_code(
    chat, *, engine, debug_prompt,
    plan_details: str, code: str, last_error: str,
    dataset_summary: str, read_recipe_hint: str,
    output_folder: Path, catalog, read_code: str,
) -> str:
    """统一 debug 入口：agent 工具循环优先，prompt 重试兜底。

    Args:
        catalog: 语义 series 目录（供 read_series_sample）
        read_code: 真实读取代码（守护层拼接，可能为空=自备读取模式）

    Returns:
        修复后代码（两个路径都失败时可能为空串）
    """
    charts_folder = output_folder / "charts"
    try:
        tools = _build_debug_tools(output_folder, charts_folder, catalog, read_code)
        message = _build_debug_message(
            plan_details=plan_details, failed_code=code, error=last_error,
            dataset_summary=dataset_summary,
            read_recipe_hint=read_recipe_hint,
        )
        new_code, logs = await debug_with_agent(chat, tools=tools, message=message)
        for line in logs:
            logger.info("debug agent", log=line)
        if new_code.strip():
            return new_code
        logger.warning("debug agent 无有效产出，退回 prompt 重试")
    except Exception as e:
        logger.warning("debug agent 异常，退回 prompt 重试", error=str(e))

    # fallback：原 prompt 重试路径
    from service.pipeline.chart_generator import _invoke_llm
    content = await _invoke_llm(engine, chat, debug_prompt, {
        "plan_details": plan_details,
        "failed_code": code,
        "error_message": last_error,
        "data_preview": "",
        "dataset_summary": dataset_summary,
        "user_config": "(未提供)",
        "read_recipe_hint": read_recipe_hint,
    })
    return extract_code_from_response(content)