"""plan 确定性校验器（零 LLM，v4 守护层）。

校验规则：
- chart_type 白名单（不在白名单 -> 丢弃）
- 引用列（x_axis/y_axis）⊆ 所选 series 的行标签列 + 列标签列（否则 -> 丢弃，不可恢复）
- series_id 存在且可加载；被选中的 series 做一次加载校验
- 计划契约字段（analysis_task / ambiguities / assumptions / confidence /
  clarification）做确定性归一化，并把校验报告写回 plan["validation"]

处置策略（降级不丢弃）：
- series_id 缺失 / 不存在 -> 改用主 series（第一个 time_series，否则第一个）并标 degraded=true
- 无目录（series 构建失败）-> 不校验 series，plan 原样放行

设计来源：docs/论文参考与系统设计.md 的 D1/D2/D5。
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


def _new_report() -> dict:
    """创建一份结构化计划校验报告。"""
    return {
        "ok": True,
        "stage": "plan",
        "degraded": False,
        "contract_complete": False,
        "requires_clarification": False,
        "warnings": [],
        "errors": [],
        "ambiguities": [],
        "assumptions": [],
    }


def ensure_plan_contract(plan: dict, report: dict | None = None) -> dict:
    """补齐并归一化计划契约字段。

    LLM 输出可能是字符串、百分比或缺失字段；这里只做确定性的类型归一化，
    不替模型编造歧义或假设。无法识别的置信度会丢弃并记入校验报告。
    """
    if not isinstance(plan, dict):
        return plan

    report = report if report is not None else _new_report()
    plan.setdefault("analysis_task", "")
    plan.setdefault("ambiguities", [])
    plan.setdefault("assumptions", [])
    plan.setdefault("clarification", [])
    plan.setdefault("confidence", None)

    plan["analysis_task"] = str(plan.get("analysis_task") or "").strip().lower()

    for key in ("ambiguities", "clarification"):
        value = plan.get(key)
        if value is None or value == "":
            plan[key] = []
        elif isinstance(value, (str, dict)):
            plan[key] = [value]
        elif not isinstance(value, list):
            plan[key] = [value]

    assumptions = plan.get("assumptions")
    if assumptions is None or assumptions == "":
        plan["assumptions"] = []
    elif isinstance(assumptions, str):
        plan["assumptions"] = [assumptions]
    elif not isinstance(assumptions, list):
        plan["assumptions"] = [assumptions]

    confidence = plan.get("confidence")
    if isinstance(confidence, str):
        try:
            confidence = float(confidence.strip())
        except ValueError:
            report["warnings"].append(f"无法识别 confidence={plan.get('confidence')!r}，已置空")
            confidence = None
    if isinstance(confidence, (int, float)) and 1 < confidence <= 100:
        confidence = confidence / 100
    if confidence is not None and not (0 <= confidence <= 1):
        report["warnings"].append(f"confidence 超出 0-1：{confidence!r}，已置空")
        confidence = None
    plan["confidence"] = confidence

    return plan


def _attach_report(plan: dict, report: dict) -> dict:
    """把报告写回 plan，补充契约完整度和澄清需求。"""
    report["requires_clarification"] = bool(plan.get("clarification"))
    report["ambiguities"] = plan.get("ambiguities", [])
    report["assumptions"] = plan.get("assumptions", [])
    report["contract_complete"] = bool(
        plan.get("analysis_task") and plan.get("confidence") is not None
    )
    plan["validation"] = report
    return report


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


def _series_is_readable(series) -> tuple[bool, str]:
    """用 parquet 元数据校验 series 可读，避免规划期加载整表。

    Returns:
        (是否可读, 失败原因)。元数据读取失败时退回有界读取一行，兼容非
        parquet 或旧格式文件。
    """
    data_path = str(getattr(series, "data_path", "") or "")
    if not data_path:
        return False, "缺少数据文件"
    try:
        import pyarrow.parquet as pq

        schema = pq.ParquetFile(data_path).schema_arrow
        if not schema.names:
            return False, "parquet 没有列"
        return True, ""
    except Exception as metadata_error:
        try:
            load_series_df(series, limit=1)
            return True, ""
        except Exception as read_error:
            return False, str(read_error or metadata_error)


def _resolve_series(plan: dict, catalog: SeriesCatalog | None, agent_logs: list,
                    tried: dict | None = None, report: dict | None = None) -> dict:
    """校验并解析 plan 的 series_id，必要时降级主 series。

    Args:
        tried: series_id -> 是否已加载通过的缓存
        report: 结构化校验报告，降级原因会写入 warnings

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
        if report is not None:
            report["degraded"] = True
            report["warnings"].append(f"series 降级为 {fallback.series_id}：{reason}")
        agent_logs.append(f"⚠️ plan {plan.get('plan_id')} 降级为 {fallback.series_id}（{reason}）")
        return {"ok": True, "degraded": True, "reason": reason}

    series = catalog.by_id(series_id) if series_id else None
    if series is None:
        return _degrade(f"series_id 缺失或不存在: {series_id!r}")

    if series_id in tried:
        return {"ok": tried[series_id], "degraded": not tried[series_id], "reason": ""}
    readable, reason = _series_is_readable(series)
    tried[series_id] = readable
    if readable:
        return {"ok": True, "degraded": False, "reason": ""}
    return _degrade(f"series 加载失败: {reason}")


def validate_one_plan(plan: dict, catalog: SeriesCatalog | None, profile, agent_logs: list,
                      tried: dict | None = None) -> bool:
    """校验单个 plan，通过/降级返回 True，不可恢复丢弃返回 False。

    无论通过还是丢弃，都会把结构化报告写入 plan["validation"]。
    """
    if not isinstance(plan, dict):
        return False

    report = _new_report()
    ensure_plan_contract(plan, report)
    plan_id = plan.get("plan_id", "?")

    # 1. chart_type 白名单
    chart_type = str(plan.get("chart_type", "")).strip().lower()
    if chart_type and chart_type not in CHART_TYPE_WHITELIST:
        msg = f"chart_type 不在白名单（{chart_type}）"
        report["ok"] = False
        report["errors"].append({"code": "UNSUPPORTED_CHART_TYPE", "message": msg})
        _attach_report(plan, report)
        agent_logs.append(f"❌ plan {plan_id} 丢弃：{msg}")
        return False

    # 2. series 解析（含加载校验与降级）
    series_result = _resolve_series(plan, catalog, agent_logs, tried, report)

    # 3. 引用列 ⊆ 所选 series 的行/列标签列
    #    例外：声明了 transform_hint 的 plan 可引用变换产物列，只记日志不丢弃。
    chosen = catalog.by_id(plan.get("series_id", "")) if catalog else None
    if chosen is not None:
        allowed = set(chosen.label_columns())
        unknown = _referenced_columns(plan) - allowed
        if unknown and not plan.get("transform_hint"):
            msg = f"引用了不存在的列 {sorted(unknown)}"
            report["ok"] = False
            report["errors"].append({
                "code": "UNKNOWN_COLUMNS",
                "message": msg,
                "hint": f"可用列：{sorted(allowed)}",
            })
            _attach_report(plan, report)
            agent_logs.append(f"❌ plan {plan_id} 丢弃：{msg}")
            logger.warning("plan 引用列不存在", plan_id=plan_id, unknown=sorted(unknown))
            return False
        if unknown:
            note = f"引用变换产物列 {sorted(unknown)}（transform_hint 已声明，跳过列校验）"
            report["warnings"].append(note)
            agent_logs.append(f"ℹ️ plan {plan_id} {note}")

    _attach_report(plan, report)
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
