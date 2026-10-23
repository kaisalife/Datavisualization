"""图表生成 RAG 检索（从 chart_generator.py 拆出）。

检索策略（对应 docs/论文参考与系统设计.md 的 RGVisNet 落地）：
1. 查询以图表类型为核心，叠加分析任务、多系列/布局等 API 特征；
2. 不拼业务标题，避免稀释 embedding 主语义；
3. 检索后优先保留与目标图表类型一致的文档，过滤失败时回退到原始结果；
4. 去重并限制注入数量，避免把不相关/重复示例塞进生成 prompt。
"""
from __future__ import annotations

import os
import time
from collections import OrderedDict
from pathlib import Path
from threading import Lock

try:
    from Entity.plan_models import plan_get
except ImportError:
    from ..plan_models import plan_get

from service.observability import get_logger

logger = get_logger(__name__)


def _env_float(name: str, default: float) -> float:
    """读取浮点环境变量；非法值回退默认值。"""
    try:
        return float(os.getenv(name, "") or default)
    except (TypeError, ValueError):
        return default


# 同一 query 的检索结果在进程内复用：多张图同类型时查询完全一致，
# embedding + Chroma 查询约 0.8s，缓存可省掉重复检索。
# TTL 默认 10 分钟，避免知识库增量同步后长时间看不到新文档。
_CACHE_TTL = max(0.0, _env_float("CHART_RAG_CACHE_TTL", 600.0))
_CACHE_MAX = max(0, int(_env_float("CHART_RAG_CACHE_MAX", 128)))
_CACHE: "OrderedDict[tuple, tuple[float, list]]" = OrderedDict()
_CACHE_LOCK = Lock()


def _cache_get(key: tuple):
    """读取未过期的缓存；过期条目顺手删除。"""
    if _CACHE_TTL <= 0 or _CACHE_MAX <= 0:
        return None
    now = time.monotonic()
    with _CACHE_LOCK:
        item = _CACHE.get(key)
        if item is None:
            return None
        created_at, docs = item
        if now - created_at > _CACHE_TTL:
            _CACHE.pop(key, None)
            return None
        _CACHE.move_to_end(key)
        return docs


def _cache_set(key: tuple, docs: list) -> None:
    """写入缓存并按 LRU 淘汰；只缓存成功返回的结果。"""
    if _CACHE_TTL <= 0 or _CACHE_MAX <= 0:
        return
    with _CACHE_LOCK:
        _CACHE[key] = (time.monotonic(), docs)
        _CACHE.move_to_end(key)
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)


def _cached_retrieve(retriever, query: str) -> list:
    """带 TTL/LRU 的检索入口；检索异常原样抛出，由调用方降级。

    缓存键是 ``(retriever, query)``：检索器是进程内单例，不同测试/重建的
    检索器不会互相命中。检索器不可哈希时退回 ``id``。
    """
    try:
        hash(retriever)
    except TypeError:
        retriever_key = id(retriever)
    else:
        retriever_key = retriever
    key = (retriever_key, query)

    cached = _cache_get(key)
    if cached is not None:
        logger.debug("RAG 检索命中缓存", query=query)
        return cached

    docs = retriever.retrieve(query) or []
    _cache_set(key, docs)
    return docs

# 图表类型 -> 检索查询（中文功能词 + 英文类型名，匹配知识库元信息）
_CHART_QUERIES = {
    "bar": "柱状图 Bar 基础 多系列 示例",
    "line": "折线图 Line 基础 多系列 示例",
    "pie": "饼图 Pie 基础 占比 示例",
    "scatter": "散点图 Scatter 基础 示例",
    "effectscatter": "涟漪散点图 EffectScatter 基础 示例",
    "heatmap": "热力图 HeatMap 基础 示例",
    "grid": "Grid 网格布局 GridOpts 多图组合 垂直布局 水平布局",
    "funnel": "漏斗图 Funnel 基础 示例",
    "radar": "雷达图 Radar 基础 示例",
    "gauge": "仪表盘 Gauge 基础 示例",
    "boxplot": "箱线图 Boxplot 基础 示例",
    "tree": "树图 Tree 基础 示例",
    "treemap": "矩形树图 TreeMap 基础 示例",
    "map": "地图 Map 基础 示例",
    "wordcloud": "词云图 WordCloud 基础 示例",
    "liquid": "水球图 Liquid 基础 示例",
    "graph": "关系图 Graph 基础 示例",
    "parallel": "平行坐标系 Parallel 基础 示例",
    "sankey": "桑基图 Sankey 基础 示例",
    "themeriver": "主题河流图 ThemeRiver 基础 示例",
    "calendar": "日历图 Calendar 基础 示例",
    "kline": "K线图 Kline 基础 示例",
    "candlestick": "K线图 Candlestick Kline 基础 示例",
    "sunburst": "旭日图 Sunburst 基础 示例",
    "pictorialbar": "象形柱图 PictorialBar 基础 示例",
    "polar": "极坐标系 Polar 基础 示例",
    "bar3d": "3D 柱状图 Bar3D 基础 示例",
    "line3d": "3D 折线图 Line3D 基础 示例",
    "scatter3d": "3D 散点图 Scatter3D 基础 示例",
    "map3d": "3D 地图 Map3D 基础 示例",
    "surface3d": "3D 曲面图 Surface3D 基础 示例",
    "geo": "地理坐标系 Geo 基础 示例",
    "overlap": "Overlap 柱线组合 柱状图 折线图 组合 示例",
    "timeline": "时间轴 Timeline 基础 示例",
    "page": "Page 顺序多图 示例",
    "tab": "Tab 选项卡 多图 示例",
    "table": "Table 表格组件 示例",
    "dataset": "Dataset 数据集 转换 示例",
}

# 分析任务 -> 检索补充词
_ANALYSIS_QUERIES = {
    "trend": "趋势 时间序列",
    "comparison": "对比 排名",
    "composition": "占比 构成",
    "distribution": "分布",
    "relationship": "关系 相关性",
}

# Feature/ 目录高级用法文档的触发规则：(触发词集合, 补充检索 query)。
# 触发扫描只看 plan 的 LLM 文案字段（plan_name/chart_title/chart_reason/transform_hint/
# assumptions），不拼业务标题进主 query——Feature 文档按触发词单独检索。
_FEATURE_RULES: tuple[tuple[frozenset[str], str], ...] = (
    (
        frozenset({"目标线", "均值线", "平均线", "警戒线", "预算线", "基准线", "达标线", "markline"}),
        "markLine 参考线 目标线 均值线 示例",
    ),
    (
        frozenset({"参考区间", "旺季", "波动带", "高亮区间", "markarea"}),
        "markArea 参考区间 高亮时段 示例",
    ),
    (
        frozenset({"断轴", "离群值", "跨度", "axisbreak"}),
        "断轴 axisBreak 离群值 数值轴 示例",
    ),
    (
        frozenset({"标签重叠", "标签挤", "labelLayout", "hotoverlap"}),
        "数据标签重叠 labelLayout hideOverlap 示例",
    ),
    (
        frozenset({"富文本", "提示框自定义", "涨跌箭头"}),
        "tooltip 富文本 JsCode 自定义 提示框 示例",
    ),
    (
        frozenset({"数据缩放", "滚动浏览", "长序列", "datazoom"}),
        "dataZoom 数据缩放 长序列 slider 示例",
    ),
    (
        frozenset({"切换动画", "过渡动画", "universaltransition"}),
        "universalTransition 系列切换 过渡动画 示例",
    ),
)

_MAX_FEATURE_DOCS = 2

# 图表类型 -> 知识库目录名（过滤 source 用）；未列出的按小写名匹配
_CHART_FOLDER_ALIASES = {
    "kline": "candlestick",
    "heatmap": "heatmap",
    "treemap": "treemap",
    "effectscatter": "effectscatter",
    "wordcloud": "wordcloud",
    "themeriver": "themeriver",
}

_DEFAULT_MAX_DOCS = 4


def _normalize_chart_key(value: str) -> str:
    """把 Bar / HeatMap / heat_map 统一成小写无分隔形式。"""
    return str(value or "").strip().lower().replace("_", "").replace("-", "").replace(" ", "")


def _plan_dict(chart_type_or_plan) -> tuple[str, dict]:
    """兼容旧的字符串参数和新的 plan dict 参数。"""
    if isinstance(chart_type_or_plan, dict):
        plan = chart_type_or_plan
        return str(plan_get(plan, "chart_type", "") or ""), plan
    return str(chart_type_or_plan or ""), {}


def build_rag_query(chart_type_or_plan: str | dict = "") -> str:
    """为图表类型/plan 构造检索 query（纯函数，便于测试）。

    兼容 ``build_rag_query("Bar")`` 的旧调用；传入 plan dict 时会额外拼接
    analysis_task、多系列、变换和布局等特征，但不拼业务标题。
    """
    raw, plan = _plan_dict(chart_type_or_plan)
    key = _normalize_chart_key(raw)

    base = _CHART_QUERIES.get(key)
    if not base:
        base = f"{raw.strip() or '图表'} 图表示例"

    extras: list[str] = []
    if plan:
        task = str(plan_get(plan, "analysis_task", "") or "").strip().lower()
        if task in _ANALYSIS_QUERIES:
            extras.append(_ANALYSIS_QUERIES[task])

        y_axis = plan_get(plan, "y_axis", None)
        if isinstance(y_axis, list) and len(y_axis) > 1:
            extras.append("多系列")

        if str(plan_get(plan, "transform_hint", "") or "").strip():
            extras.append("数据变换")

        layout = plan_get(plan, "layout", None)
        if isinstance(layout, dict):
            if layout.get("grid_top") or layout.get("grid_bottom"):
                extras.append("布局边距")
            if layout.get("legend_pos"):
                extras.append("图例")

    if not extras:
        return base
    # 去重且保持顺序
    deduped = list(dict.fromkeys(extras))
    return " ".join([base, *deduped])


def infer_doc_chart_type(doc) -> str:
    """从文档元数据/来源路径推断图表类型，供检索过滤。

    知识库按 ``RAG_Data/<Bar|Line|...>/xxx.md`` 组织；TextLoader 会把
    ``source`` 写进 metadata。没有 source 的假文档返回空串，走回退逻辑。
    """
    metadata = getattr(doc, "metadata", None) or {}
    explicit = metadata.get("chart_type")
    if explicit:
        return _normalize_chart_key(str(explicit))

    source = metadata.get("source")
    if not source:
        return ""
    try:
        folder = Path(str(source)).parent.name
    except Exception:
        return ""
    return _normalize_chart_key(folder)


def filter_reference_docs(docs: list, plan: dict, max_docs: int = _DEFAULT_MAX_DOCS) -> list:
    """按目标图表类型过滤、去重并限制注入数量。

    过滤结果为空时回退到原始 docs（知识库目录命名不一致/旧文档时仍能工作）。
    """
    if not docs:
        return []

    target = _normalize_chart_key(str(plan_get(plan, "chart_type", "") or ""))
    if not target:
        selected = list(docs)
    else:
        expected = _CHART_FOLDER_ALIASES.get(target, target)
        matched = [d for d in docs if infer_doc_chart_type(d) == expected]
        selected = matched or list(docs)

    seen: set[tuple[str, str]] = set()
    result = []
    for doc in selected:
        metadata = getattr(doc, "metadata", None) or {}
        source = str(metadata.get("source") or "")
        content = str(getattr(doc, "page_content", "") or "")
        key = (source, content[:160])
        if key in seen:
            continue
        seen.add(key)
        result.append(doc)
        if len(result) >= max(1, int(max_docs)):
            break
    return result


def _plan_feature_text(plan: dict) -> str:
    """拼出用于 Feature 触发扫描的 plan 文案（LLM 写的语义字段）。"""
    parts = [
        str(plan_get(plan, k, "") or "")
        for k in ("plan_name", "chart_title", "chart_reason", "transform_hint")
    ]
    assumptions = plan_get(plan, "assumptions", None)
    if isinstance(assumptions, list):
        parts.extend(str(a) for a in assumptions[:5])
    return " ".join(parts)


def plan_feature_queries(plan: dict) -> list[str]:
    """按 plan 文案扫描 Feature 触发词，返回去重的补充检索 query（最多 2 条）。"""
    text = _plan_feature_text(plan).lower()
    queries: list[str] = []
    for triggers, query in _FEATURE_RULES:
        if any(t in text for t in triggers) and query not in queries:
            queries.append(query)
    return queries[:_MAX_FEATURE_DOCS]


def _retrieve_feature_docs(retriever, plan: dict, max_docs: int = _MAX_FEATURE_DOCS) -> str:
    """检索 Feature/ 目录高级用法文档（失败静默降级，不影响主检索）。"""
    if retriever is None:
        return ""

    picked: list = []
    for query in plan_feature_queries(plan):
        try:
            docs = _cached_retrieve(retriever, query)
        except Exception as e:
            logger.warning("Feature 文档检索失败", query=query, error=str(e))
            break
        feature_docs = [
            d for d in docs
            if infer_doc_chart_type(d) == "feature"
            and d not in picked
        ]
        if feature_docs:
            picked.append(feature_docs[0])

    return "\n\n---\n\n".join(str(getattr(d, "page_content", "")) for d in picked)


def retrieve_reference_docs(retriever, plan: dict, max_docs: int = _DEFAULT_MAX_DOCS) -> str:
    """按 plan 的图表类型/分析任务检索 Pyecharts 参考文档。

    Args:
        retriever: RAGRetriever（None 时返回空串）
        plan: 计划 dict
        max_docs: 最多注入的示例数量

    Returns:
        参考文档拼接文本；无结果返回空串
    """
    if retriever is None:
        return ""

    chart_type = plan_get(plan, "chart_type", "Line")
    search_query = build_rag_query(plan)

    logger.info("正在检索相关文档", search_query=search_query, chart_type=chart_type)
    try:
        docs = _cached_retrieve(retriever, search_query)
        if not docs:
            logger.warning("未找到相关示例", chart_type=chart_type)
            return ""
        selected = filter_reference_docs(docs, plan, max_docs=max_docs)
        if not selected:
            logger.warning("检索结果被过滤为空", chart_type=chart_type, raw_count=len(docs))
            return ""
        logger.info(
            "找到示例",
            count=len(selected),
            raw_count=len(docs),
            chart_type=chart_type,
        )
        main_text = "\n\n---\n\n".join(doc.page_content for doc in selected)
        # 高级用法（markLine/断轴/labelLayout…）：按 plan 文案触发词补检索 Feature 文档
        feature_text = _retrieve_feature_docs(retriever, plan)
        if feature_text:
            return f"{main_text}\n\n---\n\n{feature_text}"
        return main_text
    except Exception as e:
        logger.warning("检索失败", error=str(e))
        return ""
