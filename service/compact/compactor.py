import re
from typing import List, Optional

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from service.budget.token_budget import count_tokens, count_messages_tokens


LARGE_CONTENT_THRESHOLD = 2000
MICROCOMPACT_PLACEHOLDER = "<see artifact: content compacted, {n} tokens>"
COMPACT_BOUNDARY_MARKER = "--- compact_boundary ---"

NO_TOOLS_PREAMBLE = (
    "CRITICAL: Respond with TEXT ONLY. 不要调用任何工具，不要写代码，只输出压缩摘要文本。"
)

BASE_COMPACT_PROMPT = """{preamble}

你是一个会话压缩器。请把以下完整对话历史压缩为结构化摘要，必须包含这 9 个部分（用 markdown 标题分隔）。保留所有关键决策、图表类型选择、数据字段名、错误信息，丢弃冗余的代码全文和重复内容。

## 1. 主要请求
用户的原始需求与目标。

## 2. 关键技术概念
涉及的数据字段、图表类型、技术决策。

## 3. 文件与代码段
引用的文件路径、关键代码片段（仅保留核心，非全文）。

## 4. 错误与修复
遇到的错误及修复方式。

## 5. 问题解决
已解决的问题与推理过程。

## 6. 所有用户消息
用户的所有原始消息（按顺序，简述）。

## 7. 待办任务
尚未完成的任务。

## 8. 当前工作
当前正在生成的图表及其 plan 细节（chart_type、字段映射等）。

## 9. 可选的下一步
建议的后续动作。

先在 <analysis> 标签里推理，然后产出 <summary> 标签包裹的最终摘要。

--- 对话历史 ---
{history}
"""

PARTIAL_COMPACT_PROMPT = """{preamble}

请把以下早期对话历史压缩为简洁摘要，保留关键信息（图表类型、字段名、错误）。最近 {keep_last_n} 条消息已保留，无需压缩。

--- 早期历史 ---
{history}
"""


_ANALYSIS_PATTERN = re.compile(r'<analysis>.*?</analysis>', re.DOTALL)
_SUMMARY_PATTERN = re.compile(r'<summary>(.*?)</summary>', re.DOTALL)


def format_compact_summary(text: str) -> str:
    """剥离 <analysis> 块，只留 <summary> 内容。无 summary 标签则返回原文（去 analysis）。"""
    summary_match = _SUMMARY_PATTERN.search(text)
    if summary_match:
        return summary_match.group(1).strip()
    cleaned = _ANALYSIS_PATTERN.sub('', text).strip()
    return cleaned


def _replace_large_content(content: str, model: str = "gpt-4o") -> str:
    """把超长内容块替换为占位符。"""
    if not content:
        return content
    tokens = count_tokens(content, model)
    if tokens <= LARGE_CONTENT_THRESHOLD:
        return content
    return MICROCOMPACT_PLACEHOLDER.format(n=tokens)


def microcompact_messages(messages: List[BaseMessage],
                          model: str = "gpt-4o") -> List[BaseMessage]:
    """1级压缩：原地剥离大块内容，替换为占位符，无模型调用。"""
    result = []
    for msg in messages:
        content = getattr(msg, "content", str(msg))
        if isinstance(content, str):
            new_content = _replace_large_content(content, model)
            if new_content != content:
                if isinstance(msg, SystemMessage):
                    result.append(SystemMessage(content=new_content))
                elif isinstance(msg, AIMessage):
                    result.append(AIMessage(content=new_content))
                else:
                    result.append(HumanMessage(content=new_content))
            else:
                result.append(msg)
        else:
            result.append(msg)
    return result


def snip_compact(messages: List[BaseMessage],
                 boundary: float = 0.5) -> List[BaseMessage]:
    """5级压缩：按边界比例切片，保留后 boundary 比例的历史。

    boundary=0.5 保留最近一半消息。SystemMessage 始终保留。
    """
    if boundary >= 1.0 or len(messages) <= 2:
        return list(messages)

    system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
    non_system = [m for m in messages if not isinstance(m, SystemMessage)]

    keep_count = max(1, int(len(non_system) * boundary))
    kept = non_system[-keep_count:]

    result = list(system_msgs)
    result.append(SystemMessage(content=f"{COMPACT_BOUNDARY_MARKER} 早期 {len(non_system) - keep_count} 条消息已截断"))
    result.extend(kept)
    return result


def _messages_to_text(messages: List[BaseMessage]) -> str:
    """把消息列表转为文本。"""
    parts = []
    for m in messages:
        role = "System" if isinstance(m, SystemMessage) else ("AI" if isinstance(m, AIMessage) else "Human")
        content = getattr(m, "content", str(m))
        parts.append(f"[{role}] {content}")
    return "\n\n".join(parts)


async def partial_compact(messages: List[BaseMessage],
                          chat,
                          keep_last_n: int = 6,
                          model: str = "gpt-4o") -> List[BaseMessage]:
    """2级压缩：压缩 keep_last_n 之前的历史，模型调用 PARTIAL_COMPACT_PROMPT。"""
    system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
    non_system = [m for m in messages if not isinstance(m, SystemMessage)]

    if len(non_system) <= keep_last_n:
        return list(messages)

    to_compress = non_system[:-keep_last_n]
    kept_recent = non_system[-keep_last_n:]

    history_text = _messages_to_text(to_compress)
    prompt = PARTIAL_COMPACT_PROMPT.format(
        preamble=NO_TOOLS_PREAMBLE,
        keep_last_n=keep_last_n,
        history=history_text,
    )

    response = await chat.ainvoke(prompt)
    content = getattr(response, "content", str(response))
    summary = format_compact_summary(content)

    result = list(system_msgs)
    result.append(SystemMessage(
        content=f"{COMPACT_BOUNDARY_MARKER} 早期 {len(to_compress)} 条消息压缩摘要:\n{summary}"
    ))
    result.extend(kept_recent)
    return result


async def full_compact(messages: List[BaseMessage],
                       chat,
                       model: str = "gpt-4o") -> List[BaseMessage]:
    """3级压缩：整段会话压缩，模型调用 BASE_COMPACT_PROMPT（9 section），返回单条 SystemMessage。"""
    history_text = _messages_to_text(messages)
    prompt = BASE_COMPACT_PROMPT.format(
        preamble=NO_TOOLS_PREAMBLE,
        history=history_text,
    )

    response = await chat.ainvoke(prompt)
    content = getattr(response, "content", str(response))
    summary = format_compact_summary(content)

    return [SystemMessage(
        content=f"{COMPACT_BOUNDARY_MARKER} 完整会话压缩摘要:\n{summary}"
    )]


def reactive_compact_on_overflow(messages: List[BaseMessage],
                                 error: Optional[Exception] = None,
                                 model: str = "gpt-4o") -> List[BaseMessage]:
    """4级压缩：上下文溢出时降级，先 microcompact 再 snip（无模型调用，快速降级）。"""
    compacted = microcompact_messages(messages, model)
    total_tokens = count_messages_tokens(compacted, model)
    if total_tokens > LARGE_CONTENT_THRESHOLD * 10:
        compacted = snip_compact(compacted, boundary=0.5)
    return compacted


def estimate_messages_tokens(messages: List[BaseMessage],
                             model: str = "gpt-4o") -> int:
    """估算消息列表总 token 数。"""
    return count_messages_tokens(messages, model)
