"""结构化上下文卡片（Context Cards）。

对应 docs/论文参考与系统设计.md 的 D6：
- 把“当前需求 / 数据概览 / 图表计划 / 校验结果 / 产物”压缩成少量可展示卡片；
- 卡片同时用于前端展示和后续会话摘要，不把完整数据/代码塞进上下文；
- 只使用已产出的 plan / profile / generation 结果，不调用 LLM。

本模块保持纯函数风格，便于在 agent 流水线和固定流水线共用。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from service.observability import get_logger

try:
    from Entity.plan_models import plan_get
except ImportError:  # pragma: no cover - 包内相对导入
    from ..plan_models import plan_get

logger = get_logger(__name__)

MAX_CARD_ITEMS = 12


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _as_list(value: Any) -> list:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    return [value]


def _item_text(item: Any) -> str:
    """把 assumptions/ambiguities 的字符串或对象转成一行可读文本。"""
    if isinstance(item, dict):
        text = (
            item.get("description")
            or item.get("question")
            or item.get("kind")
            or item.get("text")
            or ""
        )
        options = item.get("options")
        if options:
            text = f"{text}（候选：{', '.join(str(o) for o in options)}）"
        return str(text).strip()
    return str(item).strip()


def _card(
    card_id: str,
    kind: str,
    title: str,
    *,
    text: str = "",
    items: list | None = None,
    status: str = "info",
    meta: dict | None = None,
) -> dict:
    return {
        "id": card_id,
        "kind": kind,
        "title": title,
        "text": text,
        "items": [str(i) for i in (items or []) if str(i).strip()][:MAX_CARD_ITEMS],
        "status": status,
        "meta": meta or {},
    }


def _data_card(profile) -> dict:
    if profile is None:
        return _card(
            "data", "data", "数据概览",
            text="未提供数据画像",
            status="warning",
        )

    schema = getattr(profile, "schema", None) or []
    column_names = [
        _as_text(c.get("name")) for c in schema
        if isinstance(c, dict) and c.get("name")
    ]
    catalog = getattr(profile, "series_catalog", None)
    series_count = len(getattr(catalog, "series", []) or []) if catalog else 0
    degraded = bool(getattr(profile, "degraded", False))
    degraded_reason = _as_text(getattr(profile, "degraded_reason", ""))

    items = []
    source_kind = _as_text(getattr(profile, "source_kind", ""))
    table_name = _as_text(getattr(profile, "table_name", ""))
    if source_kind or table_name:
        items.append(f"来源：{source_kind or '未知'} / {table_name or '未命名'}")
    row_count = getattr(profile, "row_count", None)
    if row_count is not None:
        items.append(f"规模：{row_count} 行 × {len(column_names)} 列")
    if column_names:
        items.append(f"字段：{', '.join(column_names[:10])}")
    if series_count:
        items.append(f"可用语义 series：{series_count} 条")
    if degraded:
        items.append(f"降级原因：{degraded_reason or '未说明'}")

    return _card(
        "data", "data", "数据概览",
        text=f"{table_name or '当前数据'} 已接入" if table_name else "数据已接入",
        items=items,
        status="warning" if degraded else "success",
        meta={"table_name": table_name, "row_count": row_count, "series_count": series_count},
    )


def _plan_card(plan: dict) -> dict:
    plan_id = _as_text(plan_get(plan, "plan_id", "?"))
    title = _as_text(plan_get(plan, "plan_name", "")) or f"图表计划 {plan_id}"
    chart_type = _as_text(plan_get(plan, "chart_type", ""))
    series_id = _as_text(plan_get(plan, "series_id", ""))
    analysis_task = _as_text(plan_get(plan, "analysis_task", ""))
    x_axis = _as_text(plan_get(plan, "x_axis", ""))
    y_axis = plan_get(plan, "y_axis", None)
    if isinstance(y_axis, list):
        y_text = ", ".join(str(y) for y in y_axis)
    else:
        y_text = _as_text(y_axis)

    assumptions = [_item_text(i) for i in _as_list(plan_get(plan, "assumptions", []))]
    ambiguities = [_item_text(i) for i in _as_list(plan_get(plan, "ambiguities", []))]
    clarification = [_item_text(i) for i in _as_list(plan_get(plan, "clarification", []))]
    confidence = plan_get(plan, "confidence", None)

    items = []
    if chart_type:
        items.append(f"图表类型：{chart_type}")
    if series_id:
        items.append(f"数据系列：{series_id}")
    if analysis_task:
        items.append(f"分析任务：{analysis_task}")
    if x_axis or y_text:
        items.append(f"字段映射：x={x_axis or '-'} / y={y_text or '-'}")
    items.extend(f"假设：{a}" for a in assumptions)
    items.extend(f"歧义：{a}" for a in ambiguities)
    items.extend(f"待确认：{a}" for a in clarification)
    if confidence is not None:
        items.append(f"置信度：{confidence}")

    status = "warning" if (ambiguities or clarification) else "success"
    return _card(
        f"plan:{plan_id}", "plan", title,
        text=_as_text(plan_get(plan, "chart_title", "")) or "图表计划",
        items=items,
        status=status,
        meta={
            "plan_id": plan_id,
            "chart_type": chart_type,
            "series_id": series_id,
            "analysis_task": analysis_task,
            "confidence": confidence,
        },
    )


def _validation_card(plans: list[dict]) -> dict | None:
    items = []
    has_error = False
    has_warning = False
    for plan in plans:
        plan_id = _as_text(plan_get(plan, "plan_id", "?"))
        generation = plan_get(plan, "generation", {}) or {}
        report = (generation.get("validation") if isinstance(generation, dict) else None) \
            or plan_get(plan, "validation", {}) or {}
        for error in (report.get("errors") or [])[:6]:
            has_error = True
            code = error.get("code", "ERROR")
            message = error.get("message", "")
            items.append(f"plan {plan_id} [{code}] {message}")
        for warning in (report.get("warnings") or [])[:4]:
            has_warning = True
            if isinstance(warning, dict):
                message = warning.get("message", "")
            else:
                message = str(warning)
            items.append(f"plan {plan_id} 提示：{message}")

    if not items:
        return _card(
            "validation", "validation", "校验结果",
            text="计划与产物校验通过", status="success",
        )
    return _card(
        "validation", "validation", "校验结果",
        text="生成已完成，但有需要关注的问题" if not has_error else "存在未通过的校验项",
        items=items,
        status="error" if has_error else ("warning" if has_warning else "info"),
        meta={"has_error": has_error, "has_warning": has_warning},
    )


def _artifact_card(successful_charts: list, failed_plans: list) -> dict:
    items = []
    for item in successful_charts or []:
        if not isinstance(item, dict):
            continue
        plan = item.get("plan") or {}
        title = _as_text(plan_get(plan, "plan_name", "")) or _as_text(plan_get(plan, "plan_id", "图表"))
        html_path = _as_text(item.get("chart_path", ""))
        code_path = _as_text((item.get("generation") or {}).get("code_path", ""))
        if html_path:
            items.append(f"{title} → {html_path}")
        if code_path:
            items.append(f"{title} 代码 → {code_path}")

    for item in failed_plans or []:
        if not isinstance(item, dict):
            continue
        plan = item.get("plan") or {}
        title = _as_text(plan_get(plan, "plan_name", "")) or "未知计划"
        error = _as_text(item.get("error", ""))
        items.append(f"{title} 失败：{error[:200]}")

    status = "success" if successful_charts and not failed_plans else (
        "error" if failed_plans and not successful_charts else ("warning" if failed_plans else "info")
    )
    return _card(
        "artifacts", "artifact", "产物",
        text=f"成功 {len(successful_charts or [])} 个 / 失败 {len(failed_plans or [])} 个",
        items=items,
        status=status,
        meta={
            "success_count": len(successful_charts or []),
            "failed_count": len(failed_plans or []),
        },
    )


def build_context_cards(
    user_prompt: str,
    profile=None,
    plans: list[dict] | None = None,
    successful_charts: list | None = None,
    failed_plans: list | None = None,
) -> list[dict]:
    """构建一轮任务的上下文卡片（确定性、可序列化）。"""
    plans = plans or []
    successful_charts = successful_charts or []
    failed_plans = failed_plans or []

    cards = [
        _card(
            "request", "request", "当前需求",
            text=_as_text(user_prompt) or "（未提供需求）",
            status="info",
        ),
        _data_card(profile),
    ]
    cards.extend(_plan_card(plan) for plan in plans if plan is not None)
    validation = _validation_card(plans)
    if validation is not None:
        cards.append(validation)
    cards.append(_artifact_card(successful_charts, failed_plans))
    return cards


def cards_to_prompt_text(cards: list[dict], max_chars: int = 2000) -> str:
    """把卡片压成适合塞进后续会话摘要的短文本。"""
    lines = []
    for card in cards or []:
        lines.append(f"[{card.get('title', '')}] {card.get('text', '')}")
        for item in card.get("items", [])[:6]:
            lines.append(f"- {item}")
    text = "\n".join(line for line in lines if line.strip())
    if len(text) > max_chars:
        text = text[:max_chars] + "…"
    return text


def write_context_cards(output_folder: str | Path, cards: list[dict]) -> Path:
    """把上下文卡片落盘到 plans/context_cards.json。"""
    plans_folder = Path(output_folder) / "plans"
    plans_folder.mkdir(parents=True, exist_ok=True)
    path = plans_folder / "context_cards.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cards, f, ensure_ascii=False, indent=2)
    logger.info("上下文卡片已保存", path=str(path), count=len(cards or []))
    return path
