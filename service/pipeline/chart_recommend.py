"""数据驱动的图表类型推荐与 plan 多样性守护（零 LLM）。

规划 agent 仍负责理解用户需求，但"这套数据适合什么图"不再只靠模型自由发挥：

1. series 索引携带数据形态（时间点/类别数、指标数、是否含负值），
   工具输出给出确定性建议；
2. 规划完成后，``diversify_plans`` 按数据形态校正明显不合适的类型
   （时间序列 >3 个点却画柱/饼、饼图含负值等），并保证 2-4 个 plan
   覆盖趋势 / 对比 / 构成 / 分布等不同角度，而不是同一份数据换标题反复画柱状图。

约束：
- 用户明确点名的图表类型（如"柱状图"）不会被自动改掉；
- 用户指定的图表数量（如"画两个图"）是硬上限；
- 没有数据支撑的角度不会硬造，宁可少画。
"""
from __future__ import annotations

import re
from typing import Any

from service.data_ingestion.series import load_series_df
from service.data_ingestion.series.models import SemanticSeries, SeriesCatalog
from service.data_ingestion.series.shape import (
    compute_series_shape,
    format_shape_summary,
    suggest_chart_types,
)

# 常用图表类型的规范写法（plan 里允许大小写混写）
_DISPLAY = {
    "line": "Line",
    "bar": "Bar",
    "scatter": "Scatter",
    "pie": "Pie",
    "area": "Area",
    "histogram": "Histogram",
    "boxplot": "Boxplot",
    "heatmap": "Heatmap",
    "candlestick": "Candlestick",
    "radar": "Radar",
    "funnel": "Funnel",
    "gauge": "Gauge",
    "treemap": "Treemap",
    "wordcloud": "WordCloud",
    "graph": "Graph",
    "parallel": "Parallel",
    "sankey": "Sankey",
    "themeriver": "ThemeRiver",
    "sunburst": "Sunburst",
}

# 图表类型 -> 分析角度（用于去重与覆盖检查）
_FAMILY = {
    "line": "trend",
    "area": "trend",
    "candlestick": "trend",
    "bar": "comparison",
    "pie": "composition",
    "treemap": "composition",
    "funnel": "composition",
    "sunburst": "composition",
    "scatter": "relationship",
    "heatmap": "relationship",
    "graph": "relationship",
    "histogram": "distribution",
    "boxplot": "distribution",
}

# 标题里出现这些词时，不能随意把图改成另一分析角度
_RANKING_WORDS = ("排名", "排序", "降序", "升序", "top", "Top", "TOP")
_COMPOSITION_WORDS = ("占比", "构成", "份额", "结构", "组成", "比例")
_TREND_WORDS = ("趋势", "走势", "变化", "增长", "同比", "环比")

# 用户需求里的分析角度关键词（按出现位置排序）
_STYLE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "trend": ("趋势", "走势", "随时间", "变化", "增长", "同比", "环比"),
    "comparison": ("对比", "比较", "排名", "排行", "高低", "差异"),
    "composition": ("占比", "构成", "份额", "结构", "组成"),
    "distribution": ("分布", "直方图", "箱线"),
    "relationship": ("关系", "相关", "散点", "热力"),
}

# 中英文类型别名；中文按子串匹配，英文按整词匹配
_CHART_ALIASES: dict[str, tuple[str, ...]] = {
    "bar": ("柱状图", "柱形图", "条形图", "柱状", "条形", "bar chart", "bar"),
    "line": ("折线图", "折线", "曲线图", "趋势图", "line chart", "line"),
    "area": ("面积图", "area chart", "area"),
    "pie": ("饼图", "环形图", "pie chart", "pie"),
    "scatter": ("散点图", "散点", "scatter plot", "scatter"),
    "histogram": ("直方图", "histogram"),
    "boxplot": ("箱线图", "箱型图", "盒须图", "boxplot", "box plot"),
    "heatmap": ("热力图", "热图", "heatmap", "heat map"),
    "radar": ("雷达图", "radar"),
    "funnel": ("漏斗图", "funnel"),
    "gauge": ("仪表盘", "仪表图", "gauge"),
    "treemap": ("矩形树图", "树状图", "treemap", "tree map"),
    "wordcloud": ("词云图", "词云", "wordcloud", "word cloud"),
    "graph": ("关系图", "网络图", "graph"),
    "parallel": ("平行坐标图", "平行坐标", "parallel"),
    "sankey": ("桑基图", "sankey"),
    "themeriver": ("主题河流图", "themeriver", "theme river"),
    "candlestick": ("k线图", "k线", "蜡烛图", "candlestick"),
}

# 标题里的中文类型词，自动转换类型时同步改标题，避免"标题写柱状图、实际画饼图"
_TYPE_WORDS = {
    "bar": ("柱状图", "柱形图", "条形图"),
    "line": ("折线图", "曲线图", "趋势图"),
    "area": ("面积图",),
    "candlestick": ("K线图", "K线", "蜡烛图"),
    "pie": ("饼图", "环形图"),
    "scatter": ("散点图",),
    "histogram": ("直方图",),
    "boxplot": ("箱线图", "箱型图"),
    "heatmap": ("热力图", "热图"),
    "treemap": ("矩形树图", "树状图"),
    "radar": ("雷达图",),
    "funnel": ("漏斗图",),
    "gauge": ("仪表盘", "仪表图"),
}

_CN_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}

# 超过这个类别数不再自动加饼图
_PIE_MAX_CATEGORIES = 6
# 矩形树图能容纳的类别数上限（再多就只保留 Top-N 柱状图）
_TREEMAP_MAX_CATEGORIES = 20
# 同一批图里同一分析角度最多保留几张（避免两个不同指标的 Line 被误删）
_MAX_PER_FAMILY = 2
# 用户没指定数量时最多生成的图
_DEFAULT_MAX_PLANS = 4
# 仅用于 LLM 规划失败后的保守 fallback：避免把上千个设备列塞进 plan/prompt。
# 正常 planning 路径不做这个截断，由 many-series 技能按业务重要性选 Top-N。
_FALLBACK_MAX_SERIES = 8


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------
def normalize_chart_type(value: Any) -> str:
    """把 plan 里的图表类型归一成小写标识（Bar / HeatMap -> bar / heatmap）。"""
    if value is None:
        return ""
    text = str(value).strip().lower().replace("_", "").replace("-", "").replace(" ", "")
    return text


def display_chart_type(value: Any) -> str:
    """归一后的类型转回 pyecharts 常用写法（bar -> Bar）。"""
    key = normalize_chart_type(value)
    return _DISPLAY.get(key, str(value).strip() if value else "")


def chart_family(value: Any) -> str:
    """图表类型所属分析角度：trend/comparison/composition/distribution/relationship/other。"""
    return _FAMILY.get(normalize_chart_type(value), "other")


def _dedupe_types(types: list[str]) -> list[str]:
    """大小写不敏感去重，保持顺序。"""
    seen: set[str] = set()
    out: list[str] = []
    for item in types:
        key = normalize_chart_type(item)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(display_chart_type(item))
    return out


def explicit_chart_types(user_prompt: str) -> list[str]:
    """用户明确点名的图表类型（小写），如"画柱状图和折线图"。

    只有出现具体类型词才算"明确要求"；"趋势""对比"只算分析角度，
    不会锁死具体类型。
    """
    prompt = str(user_prompt or "")
    text = prompt.lower()
    found: list[str] = []
    for chart_type, aliases in _CHART_ALIASES.items():
        for alias in aliases:
            if alias.isascii():
                if re.search(rf"(?<![a-z]){re.escape(alias)}(?![a-z])", text):
                    found.append(chart_type)
                    break
            elif alias.lower() in text:
                found.append(chart_type)
                break
    return found


def _cn_to_int(token: str) -> int | None:
    """解析 1-10 的中文/阿拉伯数字。"""
    token = str(token)
    if token.isdigit():
        return int(token)
    if token in _CN_DIGITS:
        return _CN_DIGITS[token]
    if "十" in token:
        left, _, right = token.partition("十")
        tens = _CN_DIGITS.get(left, 1) if left else 1
        ones = _CN_DIGITS.get(right, 0) if right else 0
        return tens * 10 + ones
    return None


def requested_chart_count(user_prompt: str) -> int | None:
    """解析用户要求的图表数量（"画两个图"/"生成 3 张图表"），没有则 None。"""
    prompt = str(user_prompt or "")
    patterns = [
        r"(?:画|生成|制作|做|出|要|需要|给我|来)\s*([一二三四五六七八九十两\d]+)\s*(?:个|张|幅)\s*(?:图表|图|可视化)?",
        r"(?<![一二三四五六七八九十两\d])([一二三四五六七八九十两\d]+)\s*(?:个|张|幅)\s*(?:图表|图)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, prompt):
            # "一张图里包含..."不是数量要求
            tail = prompt[match.end(): match.end() + 1]
            if tail in {"里", "中", "上", "内", "的"}:
                continue
            count = _cn_to_int(match.group(1))
            if count and count > 0:
                return min(count, 6)
    return None


def requested_styles(user_prompt: str) -> list[str]:
    """用户提到的分析角度，按在 prompt 中首次出现的位置排序。"""
    prompt = str(user_prompt or "")
    positions: dict[str, int] = {}
    for style, words in _STYLE_KEYWORDS.items():
        for word in words:
            index = prompt.find(word)
            if index >= 0 and (style not in positions or index < positions[style]):
                positions[style] = index
    return [style for style, _ in sorted(positions.items(), key=lambda item: item[1])]


def series_shape(
    series: SemanticSeries,
    df=None,
    load_if_missing: bool = True,
) -> dict[str, Any]:
    """取 series 形态摘要；老 manifest 缺 shape 时按需加载 parquet 计算并回填。"""
    extra = getattr(series, "extra_semantics", None) or {}
    shape = extra.get("shape")
    if isinstance(shape, dict) and (shape.get("shape_version") or "row_labels" in shape):
        return shape
    if df is None and load_if_missing:
        try:
            df = load_series_df(series)
        except Exception:
            return {}
    if df is None:
        return {}

    shape = compute_series_shape(
        df, series.axis_kind, series.row_label_column, series.column_label_columns
    )
    # 回填到内存中的 series，同一任务内重复调用不再读盘（manifest 已落盘的不受影响）
    extra = dict(extra)
    extra["shape"] = shape
    series.extra_semantics = extra
    return shape


def _info(
    series: SemanticSeries,
    cache: dict[str, dict[str, Any]],
    load_if_missing: bool = True,
) -> dict[str, Any]:
    """series + 形态 + 常用布尔判断的缓存视图。"""
    if series.series_id in cache:
        return cache[series.series_id]

    shape = series_shape(series, load_if_missing=load_if_missing)
    axis_kind = str(series.axis_kind or "generic").lower()
    n = int(shape.get("row_labels") or 0)
    measures = int(shape.get("measure_count") or len(series.column_label_columns) or 0)
    numeric_columns = list(shape.get("numeric_columns") or series.column_label_columns)
    non_negative = bool(shape.get("non_negative", True))
    info = {
        "series": series,
        "shape": shape,
        "axis_kind": axis_kind,
        "time_like": axis_kind == "time_series" or bool(shape.get("time_like")),
        "categorical": axis_kind in {"categorical_comparison", "part_to_whole"},
        "n": n,
        "measures": measures,
        "numeric_columns": numeric_columns,
        "non_negative": non_negative,
        "pie_ok": (
            axis_kind in {"categorical_comparison", "part_to_whole"}
            and 2 <= n <= _PIE_MAX_CATEGORIES
            and non_negative
            and measures >= 1
            and not bool(shape.get("all_equal"))
        ),
        "treemap_ok": (
            axis_kind in {"categorical_comparison", "part_to_whole"}
            and 2 <= n <= _TREEMAP_MAX_CATEGORIES
            and non_negative
            and measures == 1
            and not bool(shape.get("all_equal"))
        ),
    }
    cache[series.series_id] = info
    return info


def _supports_composition(info: dict[str, Any]) -> bool:
    """是否适合看构成：少量类别用饼图，较多类别用矩形树图。"""
    return bool(info["pie_ok"] or info["treemap_ok"])


def _supports_distribution(info: dict[str, Any]) -> bool:
    """是否适合看单指标分布。

    除了显式 ``axis_kind=distribution``，还支持“没有行标签、只有一列数值”的
    generic series：这类数据本质是一组观测值，不应被强行当成类别柱状图。
    """
    if info["axis_kind"] == "distribution":
        return True
    series: SemanticSeries = info["series"]
    if info["time_like"] or series.row_label_column:
        return False
    columns = [str(c) for c in (series.column_label_columns or [])]
    numeric = info["numeric_columns"] or []
    return (
        len(columns) == 1
        and len(numeric) == 1
        and int(info["n"]) >= 5
        and not bool(info["shape"].get("all_equal"))
    )


def recommend_chart_types(
    series: SemanticSeries,
    user_prompt: str = "",
    df=None,
    load_if_missing: bool = True,
) -> dict[str, Any]:
    """结合数据形态与用户意图，给出该 series 的首选/备选图表类型。

    Returns:
        {
          "recommended": ["Line", "Area"], "alternatives": ["Bar"],
          "reason": "...", "shape": {...}, "shape_summary": "...",
          "explicit_types": [...], "requested_styles": [...]
        }
    """
    shape = series_shape(series, df=df, load_if_missing=load_if_missing)
    base, alternatives, reason = suggest_chart_types(series.axis_kind, shape)
    explicit = explicit_chart_types(user_prompt)
    styles = requested_styles(user_prompt)

    rec = list(base)
    alt = list(alternatives)
    why = reason

    if explicit:
        rec = [display_chart_type(t) for t in explicit] + rec
        why = f"用户明确要求 {', '.join(display_chart_type(t) for t in explicit)}；{reason}"
    elif styles:
        preferred_by_style: dict[str, list[str]] = {
            "trend": ["Line", "Area"],
            "composition": (
                ["Pie", "Treemap"]
                if (shape.get("non_negative", True) and 2 <= int(shape.get("row_labels") or 0) <= _PIE_MAX_CATEGORIES)
                else ["Treemap", "Bar"]
            ),
            "comparison": (
                ["Line", "Bar"]
                if (series.axis_kind == "time_series" and int(shape.get("row_labels") or 0) >= 4)
                else ["Bar"]
            ),
            "distribution": ["Histogram", "Boxplot"],
            "relationship": ["Scatter", "Heatmap"],
        }
        intent: list[str] = []
        for style in styles:
            intent.extend(preferred_by_style.get(style, []))
        if intent:
            rec = intent + rec + alt
            why = f"用户关注{'/'.join(styles)}；{reason}"

    recommended = _dedupe_types(rec)
    alternatives_clean = [
        t for t in _dedupe_types(alt) if normalize_chart_type(t) not in {
            normalize_chart_type(r) for r in recommended
        }
    ]
    return {
        "recommended": recommended,
        "alternatives": alternatives_clean,
        "reason": why,
        "shape": shape,
        "shape_summary": format_shape_summary(shape),
        "explicit_types": [display_chart_type(t) for t in explicit],
        "requested_styles": styles,
    }


# ---------------------------------------------------------------------------
# plan 多样性守护
# ---------------------------------------------------------------------------
def _plan_y(plan: dict) -> list[str]:
    """plan 的 y_axis 统一成字符串列表。"""
    y = plan.get("y_axis")
    if isinstance(y, str):
        return [y] if y else []
    if isinstance(y, (list, tuple)):
        return [str(item) for item in y if isinstance(item, (str, int, float))]
    return []


def _plan_family(plan: dict) -> str:
    return chart_family(plan.get("chart_type"))


def _plan_text(plan: dict) -> str:
    return f"{plan.get('plan_name', '')} {plan.get('chart_title', '')}"


def _title_conflicts(plan: dict, style: str) -> bool:
    """标题语义和新角度冲突时，不把这张图硬改成另一类。"""
    text = _plan_text(plan)
    if style != "comparison" and any(word in text for word in _RANKING_WORDS):
        return True
    if style in {"trend", "comparison"} and any(word in text for word in _COMPOSITION_WORDS):
        return True
    if style == "composition" and any(word in text for word in _TREND_WORDS):
        return True
    if style == "composition" and plan.get("transform_hint"):
        return True
    return False


def _replace_type_word(text: str, old_type: str, new_type: str) -> str:
    """把标题里的旧类型词替换成新类型词（没有类型词就保持原样）。"""
    text = str(text or "")
    new_words = _TYPE_WORDS.get(normalize_chart_type(new_type)) or [
        display_chart_type(new_type)
    ]
    for word in _TYPE_WORDS.get(normalize_chart_type(old_type), ()):
        if word in text:
            text = text.replace(word, new_words[0])
    return text


def _convert_plan(plan: dict, new_type: str, reason: str, logs: list[str]) -> None:
    """原地把一个 plan 改成新的图表类型，并同步标题/理由。"""
    old_type = normalize_chart_type(plan.get("chart_type"))
    new_type = normalize_chart_type(new_type)
    plan["chart_type"] = display_chart_type(new_type)
    plan["plan_name"] = _replace_type_word(plan.get("plan_name", ""), old_type, new_type)
    plan["chart_title"] = _replace_type_word(plan.get("chart_title", ""), old_type, new_type)
    old_reason = str(plan.get("chart_reason") or "").strip()
    note = (
        f"按数据形态由 {display_chart_type(old_type) or '未知类型'} "
        f"调整为 {display_chart_type(new_type)}：{reason}"
    )
    plan["chart_reason"] = f"{old_reason}；{note}" if old_reason else note
    plan["type_adjusted"] = True
    if new_type == "pie":
        plan["layout"] = {"legend_pos": "right", "grid_top": "8%", "grid_bottom": "8%"}
    logs.append(
        f"🎨 plan {plan.get('plan_id', '?')} "
        f"{display_chart_type(old_type) or '空'}→{display_chart_type(new_type)}：{reason}"
    )


def _pick_existing(
    plans: list[dict],
    style: str,
    selected_ids: set[int],
    explicit: list[str],
    order: dict[int, int],
) -> dict | None:
    """优先挑一个已存在的同角度 plan（LLM 原始优先，明确类型优先）。"""
    candidates = [
        plan for plan in plans
        if id(plan) not in selected_ids and _plan_family(plan) == style
    ]
    if not candidates:
        return None

    def key(plan: dict):
        chart_type = normalize_chart_type(plan.get("chart_type"))
        explicit_rank = 0 if chart_type in explicit else 1
        auto_rank = 1 if plan.get("auto_generated") else 0
        return (explicit_rank, auto_rank, order.get(id(plan), 999))

    return sorted(candidates, key=key)[0]


def _convert_for_style(
    plans: list[dict],
    style: str,
    selected_ids: set[int],
    explicit: list[str],
    preferred: dict[str, str],
    catalog: SeriesCatalog,
    cache: dict[str, dict[str, Any]],
    logs: list[str],
    allow_small_trend: bool = False,
) -> dict | None:
    """从已有 plan 里找一张可安全改造成目标角度的图。"""
    for plan in plans:
        if id(plan) in selected_ids:
            continue
        old_type = normalize_chart_type(plan.get("chart_type"))
        if not old_type or old_type in explicit:
            continue
        if _title_conflicts(plan, style):
            continue

        series = catalog.by_id(plan.get("series_id", ""))
        if series is None:
            continue
        info = _info(series, cache)
        old_family = chart_family(old_type)
        new_type = preferred.get(style)

        min_points = 2 if allow_small_trend else 3
        if style == "trend" and info["time_like"] and info["n"] >= min_points:
            if old_family != "trend":
                _convert_plan(plan, new_type or "Line", "时间序列应看趋势", logs)
                return plan
        elif style == "comparison":
            can_compare = info["categorical"] or (info["time_like"] and 2 <= info["n"] <= 6)
            if can_compare and old_family != "comparison":
                _convert_plan(plan, new_type or "Bar", "类别/少量时间点适合横向对比", logs)
                return plan
        elif style == "composition" and _supports_composition(info) and old_family != "composition":
            composition_type = new_type or ("Pie" if info["pie_ok"] else "Treemap")
            reason = (
                "少量非负类别适合看构成占比"
                if info["pie_ok"]
                else "类别较多但都非负，矩形树图比饼图更易读"
            )
            _convert_plan(plan, composition_type, reason, logs)
            return plan
        elif style == "distribution" and _supports_distribution(info):
            if old_family != "distribution":
                _convert_plan(plan, new_type or "Histogram", "单指标分布适合看形状", logs)
                return plan
        elif style == "relationship" and info["measures"] >= 2 and not info["time_like"]:
            if old_family != "relationship":
                _convert_plan(plan, new_type or "Scatter", "多个数值列适合看关系", logs)
                return plan
    return None


def _candidate_series(
    style: str,
    catalog: SeriesCatalog,
    selected: list[dict],
    cache: dict[str, dict[str, Any]],
    allow_small_trend: bool = False,
) -> dict[str, Any] | None:
    """为目标角度挑一条最合适、尽量未被用过的 series。"""
    used_ids = {plan.get("series_id") for plan in selected}
    candidates: list[dict[str, Any]] = []
    for series in catalog.series:
        info = _info(series, cache)
        if style == "trend":
            min_points = 2 if allow_small_trend else 3
            if info["time_like"] and info["n"] >= min_points:
                candidates.append(info)
        elif style == "comparison":
            if info["categorical"] and 2 <= info["n"] <= 30:
                candidates.append(info)
            elif info["time_like"] and 2 <= info["n"] <= 6:
                candidates.append(info)
        elif style == "composition":
            if _supports_composition(info):
                candidates.append(info)
        elif style == "distribution":
            if _supports_distribution(info):
                candidates.append(info)
        elif style == "relationship":
            if info["measures"] >= 2 and not info["time_like"]:
                candidates.append(info)
    if not candidates:
        return None
    candidates.sort(
        key=lambda info: (
            info["series"].series_id in used_ids,
            -info["n"],
            info["series"].series_id,
        )
    )
    return candidates[0]


def _new_plan_for_style(
    style: str,
    catalog: SeriesCatalog,
    selected: list[dict],
    preferred: dict[str, str],
    cache: dict[str, dict[str, Any]],
    allow_small_trend: bool = False,
) -> dict | None:
    """数据支持但 LLM 没规划到某个角度时，补一张确定性的图。"""
    info = _candidate_series(
        style, catalog, selected, cache, allow_small_trend=allow_small_trend
    )
    if info is None:
        return None

    series: SemanticSeries = info["series"]
    shape = info["shape"]
    numeric = info["numeric_columns"] or list(series.column_label_columns)
    measure = str(numeric[0]) if numeric else ""
    row_label = series.row_label_column or ""
    chart_type = normalize_chart_type(preferred.get(style, ""))
    layout = {"legend_pos": "bottom", "grid_top": "10%", "grid_bottom": "12%"}

    if style == "relationship":
        if len(numeric) < 2:
            return None
        x_axis, y_axis = str(numeric[0]), [str(numeric[1])]
        chart_type = chart_type or "scatter"
        title = f"{x_axis}与{y_axis[0]}关系"
        reason = f"数据有 {len(numeric)} 个数值列，散点图适合看两个指标的关系"
    elif style == "distribution":
        if not measure:
            return None
        x_axis, y_axis = measure, [measure]
        chart_type = chart_type or "histogram"
        title = f"{measure}分布"
        reason = f"{measure}是连续数值，直方图/箱线图适合看分布与异常值"
    elif style == "trend":
        if not row_label or not measure:
            return None
        # 多指标时间序列（多设备/多传感器）要保留同一系列的全部指标，
        # 否则用户要求“同图比较”时 fallback 只会画第一个指标。
        # 上千列时只保守取前 N 列，避免 plan/prompt 爆炸；正常路径由技能选 Top-N。
        y_axis = [str(c) for c in numeric] or [measure]
        y_axis = y_axis[:_FALLBACK_MAX_SERIES]
        x_axis = row_label
        chart_type = chart_type or "line"
        n = int(shape.get("row_labels") or info["n"])
        shown = "、".join(y_axis[:2]) + ("等" if len(y_axis) > 2 else "")
        title = f"{shown}随{row_label}变化趋势"
        reason = (
            f"数据含 {n} 个时间点、{len(y_axis)} 个指标，"
            "折线/面积图比柱状图更能表达连续变化"
        )
    elif style == "comparison":
        if not row_label or not measure:
            return None
        x_axis, y_axis = row_label, [measure]
        chart_type = chart_type or "bar"
        n = int(shape.get("row_labels") or info["n"])
        title = f"各{row_label}{measure}对比"
        reason = f"数据是 {n} 个类别的单指标对比，柱状图最适合看高低差异"
    elif style == "composition":
        if not row_label or not measure:
            return None
        x_axis, y_axis = row_label, [measure]
        use_pie = info["pie_ok"]
        chart_type = chart_type or ("pie" if use_pie else "treemap")
        n = int(shape.get("row_labels") or info["n"])
        title = f"各{row_label}{measure}{'占比' if use_pie else '构成'}"
        reason = (
            f"{n} 个非负类别可构成整体，饼图用于看各部分的份额"
            if use_pie
            else f"{n} 个非负类别较多，矩形树图比饼图更易读"
        )
        if use_pie:
            layout = {"legend_pos": "right", "grid_top": "8%", "grid_bottom": "8%"}
    else:
        return None

    return {
        "plan_id": "",
        "plan_name": title,
        "chart_type": display_chart_type(chart_type),
        "chart_title": title,
        "chart_reason": reason,
        "series_id": series.series_id,
        "transform_hint": "",
        "x_axis": x_axis,
        "y_axis": y_axis,
        "use_column_names": True,
        "execution_order": 0,
        "layout": layout,
        "auto_generated": True,
        "data_driven": True,
    }


def _same_metric(left: dict, right: dict) -> bool:
    """同一 series + 同一组指标（且都不是变换产物）视为重复图。"""
    return (
        left.get("series_id") == right.get("series_id")
        and set(_plan_y(left)) == set(_plan_y(right))
        and not left.get("transform_hint")
        and not right.get("transform_hint")
    )


def _catalog_styles(
    catalog: SeriesCatalog,
    cache: dict[str, dict[str, Any]],
) -> list[str]:
    """数据本身支持哪些分析角度（trend 优先，其次对比/构成/分布/关系）。"""
    supported: set[str] = set()
    for series in catalog.series:
        info = _info(series, cache, load_if_missing=False)
        if info["time_like"] and info["n"] >= 3:
            supported.add("trend")
        if info["categorical"] and 2 <= info["n"] <= 30:
            supported.add("comparison")
        if _supports_composition(info):
            supported.add("composition")
        if _supports_distribution(info):
            supported.add("distribution")
        if info["measures"] >= 2 and not info["time_like"]:
            supported.add("relationship")
    return [style for style in ("trend", "comparison", "composition", "distribution", "relationship") if style in supported]


def _only_requested(user_prompt: str) -> bool:
    """用户是否用了"只看/仅要"这类排他表述。"""
    return bool(re.search(r"[只仅]\s*(?:要|需|看|画|生成|保留)", str(user_prompt or "")))


def _diversify(
    plans: list[dict],
    catalog: SeriesCatalog,
    user_prompt: str,
    max_plans: int,
    logs: list[str],
) -> list[dict]:
    work = [dict(plan) for plan in plans]
    explicit = explicit_chart_types(user_prompt)
    user_styles = requested_styles(user_prompt)
    for chart_type in explicit:
        style = chart_family(chart_type)
        if style not in user_styles:
            user_styles.append(style)

    only_mode = _only_requested(user_prompt)
    requested_count = requested_chart_count(user_prompt)
    cache: dict[str, dict[str, Any]] = {}
    data_styles = _catalog_styles(catalog, cache)

    # 允许出现的分析角度：用户要求优先，其次用户明确点名的类型；
    # 没有明确类型时再按数据能力补齐。
    allowed: list[str] = []

    def allow(style: str) -> None:
        if style and style not in allowed:
            allowed.append(style)

    for style in user_styles:
        allow(style)
    for chart_type in explicit:
        allow(chart_family(chart_type))
    if not explicit and not only_mode:
        for style in data_styles:
            allow(style)
        for plan in work:
            family = _plan_family(plan)
            if family != "other":
                allow(family)
    if only_mode:
        allowed = [style for style in allowed if style in user_styles] or allowed[:1]

    # 用户明确点名的类型作为该角度的首选（如"饼图"不会被新建成 Bar）
    preferred: dict[str, str] = {}
    for chart_type in explicit:
        preferred.setdefault(chart_family(chart_type), display_chart_type(chart_type))

    existing_count = len(work)
    if requested_count:
        target = requested_count
    elif only_mode:
        target = max(1, len(user_styles))
    elif explicit:
        target = max(1, min(max_plans, existing_count))
    elif user_styles:
        target = max(len(user_styles), min(max_plans, existing_count))
    else:
        target = min(max_plans, max(2, existing_count))
    hard_cap = 6 if requested_count else max_plans
    target = max(1, min(target, hard_cap))

    order = {id(plan): index for index, plan in enumerate(work)}
    selected: list[dict] = []
    selected_ids: set[int] = set()
    family_count: dict[str, int] = {}

    def add(plan: dict | None) -> None:
        if plan is None or id(plan) in selected_ids:
            return
        selected.append(plan)
        selected_ids.add(id(plan))
        family = _plan_family(plan)
        family_count[family] = family_count.get(family, 0) + 1

    # 用户明确要"趋势"时，2 个时间点也可以画折线；自动补角度仍要求 ≥3 个点
    trend_requested = "trend" in user_styles

    # 用户点名/明确要求的分析角度是硬需求；其余数据角度只用来补空位。
    # 关键：LLM 已经画出的有效图（如 Bar+Scatter）要优先保留，不能为了
    # "凑一个构成图"把散点图硬改成饼图。
    required_styles = list(user_styles)
    for chart_type in explicit:
        family = chart_family(chart_type)
        if family not in required_styles:
            required_styles.append(family)
    if only_mode and not required_styles:
        required_styles = allowed[:1]
    optional_styles = [] if explicit else [
        style for style in allowed if style not in required_styles
    ]
    preserve_allowed = set(required_styles) if (explicit or only_mode) else set(allowed) | {"other"}

    # 1) 先满足用户明确要求的角度（没有现成的就安全改造或按数据补一张）
    for style in required_styles:
        if len(selected) >= target:
            break
        if family_count.get(style, 0) >= 1:
            continue
        plan = _pick_existing(work, style, selected_ids, explicit, order)
        if plan is None:
            plan = _convert_for_style(
                work, style, selected_ids, explicit, preferred, catalog, cache, logs,
                allow_small_trend=trend_requested,
            )
        if plan is None:
            plan = _new_plan_for_style(
                style, catalog, selected, preferred, cache,
                allow_small_trend=trend_requested,
            )
        add(plan)

    # 2) 优先保留 LLM 已经规划好的有效图（按原顺序，同 series+指标去重）
    # preserve_allowed 含 "other"：Gauge/Liquid/WordCloud/Graph 这类不属于
    # 五大分析家族的合法图（尤其是技能/用户意图选出的单值快照图）不能因为
    # 归不进 tool 家族就被静默丢弃；总数仍由 target 上限约束。
    for plan in sorted(work, key=lambda item: (bool(item.get("auto_generated")), order.get(id(item), 999))):
        if len(selected) >= target:
            break
        if id(plan) in selected_ids:
            continue
        family = _plan_family(plan)
        if family not in preserve_allowed:
            continue
        if family_count.get(family, 0) >= _MAX_PER_FAMILY:
            continue
        if any(_same_metric(other, plan) for other in selected):
            continue
        add(plan)

    # 3) 还有空位且没有明确类型限制时，按数据能力补一个缺失角度
    for style in optional_styles:
        if len(selected) >= target:
            break
        if family_count.get(style, 0) >= 1:
            continue
        plan = _pick_existing(work, style, selected_ids, explicit, order)
        if plan is None:
            plan = _convert_for_style(
                work, style, selected_ids, explicit, preferred, catalog, cache, logs,
                allow_small_trend=trend_requested,
            )
        if plan is None:
            plan = _new_plan_for_style(
                style, catalog, selected, preferred, cache,
                allow_small_trend=trend_requested,
            )
        add(plan)

    # 4) 仍未满时，用剩余不同指标的 plan 填充（同角度最多 2 张）
    for plan in work:
        if len(selected) >= target:
            break
        if id(plan) in selected_ids:
            continue
        family = _plan_family(plan)
        if family not in preserve_allowed:
            continue
        if family_count.get(family, 0) >= _MAX_PER_FAMILY:
            continue
        if any(_same_metric(other, plan) for other in selected):
            continue
        add(plan)

    if not selected:
        selected = work[:target]

    # 3) 重新编号，保证 plan_id / execution_order 连续
    for index, plan in enumerate(selected, 1):
        plan["plan_id"] = str(index)
        plan["execution_order"] = index

    families = [chart_family(plan.get("chart_type")) for plan in selected]
    summary = " / ".join(
        f"{label} {families.count(style)}"
        for style, label in (
            ("trend", "趋势"), ("comparison", "对比"), ("composition", "构成"),
            ("distribution", "分布"), ("relationship", "关系"), ("other", "其他"),
        )
        if families.count(style)
    )
    if len(selected) != len(plans) or any(
        normalize_chart_type(a.get("chart_type")) != normalize_chart_type(b.get("chart_type"))
        for a, b in zip(selected, plans)
    ):
        logs.append(f"🎨 图表类型按数据形态优化：{len(plans)}→{len(selected)} 个 plan（{summary}）")
    return selected


def build_deterministic_plans(
    catalog: SeriesCatalog | None,
    user_prompt: str = "",
    agent_logs: list | None = None,
    max_plans: int = _DEFAULT_MAX_PLANS,
) -> list[dict]:
    """在没有 LLM plan 时，完全按数据形态生成保守计划。

    用于规划阶段彻底失败（网关 429/超时）的兜底：仍然绑定真实 series，
    避免生成阶段拿到没有 series_id 的“自主图表”而缺少注入的 df。
    """
    logs = agent_logs if agent_logs is not None else []
    if catalog is None or not catalog.series:
        return []
    try:
        return _diversify([], catalog, user_prompt, max_plans, logs)
    except Exception as exc:  # 兜底失败不能影响主流程
        logs.append(f"⚠️ 确定性计划生成失败: {exc}")
        return []


def diversify_plans(
    plans: list[dict],
    catalog: SeriesCatalog | None,
    user_prompt: str = "",
    agent_logs: list | None = None,
    max_plans: int = _DEFAULT_MAX_PLANS,
) -> list[dict]:
    """按数据形态校正图表类型并保证分析角度多样（零 LLM）。

    Args:
        plans: 规划阶段产出的 plans（校验后）
        catalog: series 目录；为空时原样返回
        user_prompt: 用户原始需求（识别明确类型/图表数量/分析角度）
        agent_logs: 前端日志列表，就地追加
        max_plans: 用户未指定数量时的上限

    Returns:
        调整后的 plans（plan_id / execution_order 已重新编号）
    """
    logs = agent_logs if agent_logs is not None else []
    if not plans or catalog is None or not catalog.series:
        return plans
    try:
        return _diversify(plans, catalog, user_prompt, max_plans, logs)
    except Exception as exc:  # 守护层失败不能影响主流程
        logs.append(f"⚠️ 图表类型多样性调整失败（保留原计划）: {exc}")
        return plans
