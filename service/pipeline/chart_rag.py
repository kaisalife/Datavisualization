"""图表生成 RAG 检索（从 chart_generator.py 拆出）。

主查询以 chart_type 为核心（RAG 索引按图表类型组织），
只叠加 chart_title 作为微弱语义提示；避免拼接 plan_description /
data_analysis 稀释 embedding 主语义。

注：当前为 per-plan 检索；P3 改任务级共享（KV 缓存前提）。
"""
from __future__ import annotations

try:
    from Entity.plan_models import plan_get
except ImportError:
    from ..plan_models import plan_get

from service.observability import get_logger

logger = get_logger(__name__)


def retrieve_reference_docs(retriever, plan: dict) -> str:
    """按 plan 的图表类型检索 pyecharts 参考文档。

    Args:
        retriever: RAGRetriever（None 时返回空串）
        plan: 计划 dict（chart_type / chart_title）

    Returns:
        参考文档拼接文本；无结果返回空串
    """
    if retriever is None:
        return ""

    chart_type = plan_get(plan, "chart_type", "Line")
    chart_title = plan_get(plan, "chart_title", "")
    search_query = f"pyecharts {chart_type} chart example"
    if chart_title:
        search_query += f" {chart_title}"

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
