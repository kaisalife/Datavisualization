"""图表生成 RAG 检索（从 chart_generator.py 拆出）。

查询以图表类型为核心：知识库文档开头带 ``图表类型 / 功能标签`` 元信息，
用「柱状图 Bar 基础 多系列 示例」这类中文功能词检索，比英文
``pyecharts Bar chart example`` 更容易命中 ``bar_base.md`` 这类基础示例。

不拼 plan_description / data_analysis / chart_title：业务标题会稀释 embedding
主语义，而标题本身已经由生成 prompt 单独提供。
"""
from __future__ import annotations

try:
    from Entity.plan_models import plan_get
except ImportError:
    from ..plan_models import plan_get

from service.observability import get_logger

logger = get_logger(__name__)

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
}


def build_rag_query(chart_type: str) -> str:
    """为图表类型构造检索 query（纯函数，便于测试）。"""
    raw = str(chart_type or "").strip()
    key = raw.lower().replace("_", "").replace(" ", "")
    if key in _CHART_QUERIES:
        return _CHART_QUERIES[key]
    # 未知类型：保留原始类型名，让向量检索仍有机会命中
    return f"{raw or '图表'} 图表示例"


def retrieve_reference_docs(retriever, plan: dict) -> str:
    """按 plan 的图表类型检索 pyecharts 参考文档。

    Args:
        retriever: RAGRetriever（None 时返回空串）
        plan: 计划 dict（chart_type）

    Returns:
        参考文档拼接文本；无结果返回空串
    """
    if retriever is None:
        return ""

    chart_type = plan_get(plan, "chart_type", "Line")
    search_query = build_rag_query(chart_type)

    logger.info("正在检索相关文档", search_query=search_query)
    try:
        docs = retriever.retrieve(search_query)
        if not docs:
            logger.warning("未找到相关示例")
            return ""
        logger.info("找到示例", count=len(docs))
        return "\n\n---\n\n".join(doc.page_content for doc in docs)
    except Exception as e:
        logger.warning("检索失败", error=str(e))
        return ""
