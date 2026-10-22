"""AI 润色：把用户的一句话需求 / 粗糙提示词，写成规范的 SKILL.md 草稿。

设计约束：

- **不落盘**：本模块只生成并校验草稿，保存仍走 ``POST /api/skills``
  （用户在技能管理界面确认后才写进用户技能目录）。
- **校验复用运行时**：草稿用 ``user_skills`` 的同一条解析/校验路径
  （slug、frontmatter 必填、正文非空、名称一致），不合规直接报错让用户改。
- **规范内置**：frontmatter 字段、正文四段结构、pyecharts 2.1 硬约束
  （真实存在的 opts 类、bar_max_width、extend_axis 双轴等）都写进 system prompt，
  避免模型编出不存在的 API 写进技能。
"""
from __future__ import annotations

import os
import re

from langchain_core.prompts import ChatPromptTemplate

from service.observability import get_logger
from service.runtime.utils import get_env_int, get_llm_extra_headers
from service.skills.user_skills import (
    SkillValidationError,
    _NAME_RE,
    _parse_skill_from_text,
    _parse_skill_text,
)

logger = get_logger("skills.polish")

# 规划层认的图表类型（Entity.plan_models.ChartType）——技能只能引用这些
_CHART_TYPES = (
    "Line", "Bar", "Scatter", "Pie", "Area", "Histogram", "Boxplot", "Heatmap",
    "Candlestick", "Radar", "Funnel", "Gauge", "Treemap", "WordCloud", "Graph",
    "Parallel", "Sankey", "ThemeRiver",
)

SKILL_POLISH_SYSTEM_PROMPT = f"""你是数据可视化项目的「技能编写专家」。用户会给你一句很粗糙的需求
（可能是业务口语、行业术语、甚至只是“帮我做个达标率图”），你要把它写成一份可直接
加载的技能文件 SKILL.md。技能会在图表规划/生成阶段被 LLM 按需读取。

## 技能文件格式（严格遵守）

文件必须以 YAML frontmatter 开头，后接 Markdown 正文。frontmatter 只支持这些字段
（除 name/description 外都可省略）：

```
---
name: 小写 slug（2–64 位小写字母/数字/连字符，必须与用户给出的技能名一致）
title: 展示名（中文，简短）
description: 一句话用途（写清“什么数据 + 什么业务问题 + 用什么图”）
chart_types: [Bar]            # 只能从下列类型选，可多个
analysis_tasks: [comparison]  # trend / comparison / composition / distribution / relationship
time_like: true               # 可选：仅适用于时间序列
min_rows: 30                  # 可选：最少行数
min_series: 5                 # 可选：最少指标列数
user_keywords: [关键词1, 关键词2]
require_keywords: true        # 可选：只有用户话术含关键词才命中（防止普通图表误用）
---
```

chart_types 只能取：{", ".join(_CHART_TYPES)}。

## 正文结构（四段，全部用中文）

1. **## 适用判断**：什么数据形态/业务问题该用这个技能；什么情况不要用（边界与反例）。
2. **## 数据加工范式**：从业务粒度到图表粒度的 pandas 变换，给可直接复制的代码。
   假设全局变量 `df` 已注入（series 数据），不要写重新读文件/建连接。
3. **## 生成要点**：pyecharts 代码骨架与关键 option；标题/轴标签写中文业务语义。
4. **## 踩坑点**：真实容易做错的地方（口径、排序、空值、坐标轴、标签重叠等）。

## pyecharts 2.1 硬约束（写进技能代码必须真实可跑）

- 只用 pyecharts（禁止 matplotlib / plotly）；每个图 `.render()`。
- 选项类必须带 `opts.` 前缀；`ThemeType` 在 `pyecharts.globals`，不是 `opts.ThemeType`。
- 柱宽用 `add_yaxis(..., bar_max_width=42)`（snake_case；`barMaxWidth` 会 TypeError）。
- 双轴（如帕累托累计占比）必须 `bar.extend_axis(yaxis=opts.AxisOpts(...))`，
  不要挂在 line 图上 `set_global_opts`（overlap 会丢掉右轴）。
- 参考线用 `opts.MarkLineOpts(data=[opts.MarkLineItem(y=80, name="80%")])` 作为
  series 参数；参考区间用 `opts.MarkAreaOpts`。
- 矩形树图类名是 `TreeMap`（大写 M）；`Grid` 边距只能
  `Grid().add(chart, grid_opts=opts.GridOpts(...))`。
- 不要编造不存在的 opts 类；不确定的写法就省略，宁缺毋滥。

## 输出要求

- 只输出 SKILL.md 的完整文本（frontmatter + 正文），不要任何解释、不要代码围栏。
- frontmatter 的 name 必须逐字等于用户指定的技能名。
- 正文要具体、可执行：不要写“根据情况调整”这类空话，给阈值/范式/代码。
"""

SKILL_POLISH_HUMAN_PROMPT = """技能名（frontmatter 的 name 必须逐字使用）：{name}
用户想要的场景 / 粗糙提示词：
{prompt}
"""


def build_polish_prompt() -> ChatPromptTemplate:
    """构造润色 prompt 模板。"""
    return ChatPromptTemplate([
        ("system", SKILL_POLISH_SYSTEM_PROMPT),
        ("human", SKILL_POLISH_HUMAN_PROMPT),
    ]).partial(name="（未指定，请你生成一个合适的 slug）")


def build_polish_chat(
    model_url: str = "",
    model_api_key: str = "",
    model_type: str = "",
):
    """构造润色用 LLM（请求级凭证 > .env 的 BASE_URL/API_KEY/MODEL_NAME）。

    与多模态 reader 同一套降级顺序；显式带 ``default_headers``（自定义网关需要）。
    """
    from dotenv import load_dotenv

    load_dotenv()

    base_url = (
        str(model_url or "").strip()
        or os.getenv("SKILL_POLISH_BASE_URL", "").strip()
        or os.getenv("BASE_URL", "").strip()
    )
    api_key = (
        str(model_api_key or "").strip()
        or os.getenv("SKILL_POLISH_API_KEY", "").strip()
        or os.getenv("API_KEY", "").strip()
    )
    model = (
        str(model_type or "").strip()
        or os.getenv("SKILL_POLISH_MODEL_NAME", "").strip()
        or os.getenv("MODEL_NAME", "").strip()
    )
    if not base_url or not api_key or not model:
        raise RuntimeError(
            "未配置润色模型：请在请求里带 model_url/model_api_key/model_type，"
            "或在 .env 设置 SKILL_POLISH_BASE_URL/SKILL_POLISH_API_KEY/SKILL_POLISH_MODEL_NAME"
        )

    from langchain_openai import ChatOpenAI

    logger.info("技能润色使用模型", model=model, base_url=base_url)
    return ChatOpenAI(
        base_url=base_url,
        api_key=api_key,
        model=model,
        temperature=0.2,
        max_tokens=get_env_int("SKILL_POLISH_MAX_TOKENS", 8192),
        timeout=get_env_int("SKILL_POLISH_TIMEOUT", 120),
        max_retries=2,
        default_headers=get_llm_extra_headers() or None,
    )


_FENCE_RE = re.compile(r"^\s*```[a-zA-Z0-9_-]*\s*\n(.*?)\n```\s*$", re.S)


def normalize_skill_markdown(text: str) -> str:
    """把模型输出规整成纯 SKILL.md：去代码围栏、去 frontmatter 之前的解释文字。"""
    cleaned = str(text or "").lstrip("\ufeff").strip()

    # 只有整段被一个围栏包住时才剥（避免误伤正文里的代码块）
    fenced = _FENCE_RE.match(cleaned)
    if fenced:
        cleaned = fenced.group(1).strip()

    # 找第一行 frontmatter 分隔符，丢掉前面的寒暄
    lines = cleaned.splitlines()
    for index, line in enumerate(lines):
        if line.strip() == "---":
            cleaned = "\n".join(lines[index:]).strip()
            break

    # 去掉尾部的围栏残留
    if cleaned.endswith("```"):
        cleaned = cleaned[: -3].rstrip()
    return cleaned


def validate_draft(content: str, *, expected_name: str | None = None) -> dict:
    """校验润色草稿（不落盘）；返回技能元数据字典。

    Raises:
        SkillValidationError: 名称/ frontmatter / 正文不合规，直接给用户可读原因。
    """
    text = normalize_skill_markdown(content)
    parsed = _parse_skill_from_text(text)
    if parsed is None:
        raise SkillValidationError(
            "生成的技能缺少合法 frontmatter（需要 --- 包裹的 name 与 description）"
        )

    name = parsed.name
    if expected_name and name != expected_name:
        raise SkillValidationError(
            f"生成的 frontmatter name（{name!r}）与请求的技能名（{expected_name!r}）不一致"
        )
    if not _NAME_RE.match(name):
        raise SkillValidationError(
            f"技能名 {name!r} 不合规：要求 2–64 位小写字母/数字/连字符"
        )

    # 走与保存相同的完整校验（正文非空等）
    parsed = _parse_skill_text(text, expected_name=name)
    return {
        "name": parsed.name,
        "title": parsed.title,
        "description": parsed.description,
        "chart_types": list(parsed.metadata.get("chart_types") or []),
        "analysis_tasks": list(parsed.metadata.get("analysis_tasks") or []),
        "user_keywords": list(parsed.metadata.get("user_keywords") or []),
        "require_keywords": bool(parsed.metadata.get("require_keywords")),
    }


async def polish_skill(chat, raw_prompt: str, name_hint: str = "") -> dict:
    """调用 LLM 生成并校验 SKILL.md 草稿。"""
    return polish_skill_sync(chat, raw_prompt, name_hint)


def polish_skill_sync(chat, raw_prompt: str, name_hint: str = "") -> dict:
    """调用 LLM 生成并校验 SKILL.md 草稿（同步版，API 路由使用）。

    刻意用同步 ``invoke``：Flask 路由本身是同步的，且该环境里 httpx 连接池
    会在多个 ``asyncio.run`` 事件循环之间复用已关闭的连接（表现为第二次调用
    "Event loop is closed"）。单次阻塞调用没有这个风险。

    Args:
        chat: 已构造的 LangChain chat model（测试可注入假模型）
        raw_prompt: 用户的一句话需求/粗糙提示词
        name_hint: 用户指定技能名（slug）；为空时由模型生成

    Returns:
        ``{"content": SKILL.md 全文, "skill": 元数据}``
    """
    if not str(raw_prompt or "").strip():
        raise SkillValidationError("prompt 不能为空")

    prompt = build_polish_prompt().invoke({
        "prompt": str(raw_prompt).strip(),
        "name": name_hint or "（未指定，请你生成一个合适的 slug）",
    })
    response = chat.invoke(prompt)
    content = getattr(response, "content", None)
    if content is None and isinstance(response, dict):
        content = response.get("content")
    text = str(content or "").strip()
    if not text:
        raise SkillValidationError(
            "模型没有返回内容（推理模型可能把 max_tokens 耗尽在思考上；"
            "可调大 SKILL_POLISH_MAX_TOKENS 后重试）"
        )

    normalized = normalize_skill_markdown(text)
    meta = validate_draft(normalized, expected_name=name_hint or None)
    return {"content": normalized, "skill": meta}
