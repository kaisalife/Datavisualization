"""plan 确定性校验器（零 LLM，v4 守护层）。

校验规则：
- chart_type 白名单（不在白名单 -> 丢弃）
- 引用列（x_axis/y_axis）⊆ 所选 series 的行标签列 + 列标签列（否则 -> 丢弃，不可恢复）
- series_id 存在且可加载；被选中的 series 做一次加载校验

处置策略（降级不丢弃）：
- series_id 缺失 / 不存在 -> 改用主 series（第一个 time_series，否则第一个）并标 degraded=true
- 无目录（series 构建失败）-> 不校验 series，plan 原样放行
"""
from __future__ import annotations

from service.data_ingestion.series import load_series_df
from service.data_ingestion.series.models import SeriesCatalog
from service.observability import get_logger

logger = get_logger(__name__)

CHART_TYPE_WHITELIST = {
    "line", "bar", "scatter", "pie", "area", "histogram", "boxplot", "heatmap",
    "candlestick", "radar", "funnel", "gauge", "treemap", "wordcloud", "graph",
    "parallel", "sankey", "themeriver",
}


def _referenced_columns(plan: dict) -> set[str]:
    """plan 引用的数据列：x_axis（str）+ y_axis（str | list）。"""
    cols: set[str] = set()
    x = plan.get("x_axis")
    if isinstance(x, str) and x:
        cols.add(x)
    y = plan.get("y_axis")
    if isinstance(y, str) and y:
        cols.add(y)
    elif isinstance(y, list):
        cols |= {c for c in y if isinstance(c, str)}
    return cols


def _primary_series(catalog: SeriesCatalog | None):
    """取主 series：第一个 time_series，否则第一个。"""
    if catalog is None or not catalog.series:
        return None
    for s in catalog.series:
        if s.axis_kind == "time_series":
            return s
    return catalog.series[0]


def _resolve_series(plan: dict, catalog: SeriesCatalog | None, agent_logs: list,
                    tried: dict | None = None) -> dict:
    """校验并解析 plan 的 series_id，必要时降级主 series。

    Args:
        tried: series_id -> 是否已加载通过的缓存

    Returns:
        校验结果 dict: {"ok", "degraded", "reason"}；降级时直接改写 plan。
    """
    tried = tried if tried is not None else {}
    series_id = plan.get("series_id", "")
    if catalog is None or not catalog.series:
        return {"ok": True, "degraded": False, "reason": "no_catalog"}

    fallback = _primary_series(catalog)

    def _degrade(reason: str) -> dict:
        if fallback is None:
            return {"ok": True, "degraded": False, "reason": f"{reason};no_series"}
        plan["series_id"] = fallback.series_id
        plan["degraded"] = True
        agent_logs.append(f"⚠️ plan {plan.get('plan_id')} 降级为 {fallback.series_id}（{reason}）")
        return {"ok": True, "degraded": True, "reason": reason}

    series = catalog.by_id(series_id) if series_id else None
    if series is None:
        return _degrade(f"series_id 缺失或不存在: {series_id!r}")

    if series_id in tried:
        return {"ok": tried[series_id], "degraded": not tried[series_id], "reason": ""}
    try:
        load_series_df(series)
        tried[series_id] = True
        return {"ok": True, "degraded": False, "reason": ""}
    except Exception as e:
        tried[series_id] = False
        return _degrade(f"series 加载失败: {e}")


def validate_one_plan(plan: dict, catalog: SeriesCatalog | None, profile, agent_logs: list,
                      tried: dict | None = None) -> bool:
    """校验单个 plan，通过/降级返回 True，不可恢复丢弃返回 False。"""
    plan_id = plan.get("plan_id", "?")

    # 1. chart_type 白名单
    chart_type = str(plan.get("chart_type", "")).strip().lower()
    if chart_type and chart_type not in CHART_TYPE_WHITELIST:
        agent_logs.append(f"❌ plan {plan_id} 丢弃：chart_type 不在白名单（{chart_type}）")
        return False

    # 2. series 解析（含加载校验与降级）
    series_result = _resolve_series(plan, catalog, agent_logs, tried)

    # 3. 引用列 ⊆ 所选 series 的行/列标签列
    #    例外：声明了 transform_hint 的 plan 可引用变换产物列，只记日志不丢弃。
    chosen = catalog.by_id(plan.get("series_id", "")) if catalog else None
    if chosen is not None:
        allowed = set(chosen.label_columns())
        unknown = _referenced_columns(plan) - allowed
        if unknown and not plan.get("transform_hint"):
            agent_logs.append(f"❌ plan {plan_id} 丢弃：引用了不存在的列 {sorted(unknown)}")
            logger.warning("plan 引用列不存在", plan_id=plan_id, unknown=sorted(unknown))
            return False
        if unknown:
            agent_logs.append(
                f"ℹ️ plan {plan_id} 引用变换产物列 {sorted(unknown)}（transform_hint 已声明，跳过列校验）"
            )

    if not series_result["degraded"]:
        agent_logs.append(f"✅ plan {plan_id} 校验通过（series: {plan.get('series_id', '-')}）")
    return True


def validate_plans(plans: list[dict], catalog: SeriesCatalog | None, profile, agent_logs: list) -> list[dict]:
    """批量校验 plans（零 LLM）。

    Args:
        plans: LLM 产出的计划列表
        catalog: 语义 series 目录（None 表示无目录，跳过 series 校验）
        profile: DataProfile（保留签名兼容）
        agent_logs: 前端展示日志，就地追加

    Returns:
        校验后的 plans（通过的 + 降级的；丢弃的不在内）
    """
    validated = []
    tried: dict = {}
    for p in plans:
        if validate_one_plan(p, catalog, profile, agent_logs, tried):
            validated.append(p)
    logger.info(
        "plan 校验完成",
        total=len(plans), kept=len(validated), dropped=len(plans) - len(validated),
    )
    return validated