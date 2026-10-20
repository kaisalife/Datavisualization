"""RAG 检索 query 与容错回归（不加载真实模型）。"""
from __future__ import annotations

from types import SimpleNamespace

from service.pipeline.chart_rag import build_rag_query, retrieve_reference_docs


class _FakeRetriever:
    def __init__(self, docs=None, error: Exception | None = None):
        self.docs = docs or []
        self.error = error
        self.queries: list[str] = []

    def retrieve(self, query: str):
        self.queries.append(query)
        if self.error:
            raise self.error
        return self.docs


def test_known_chart_types_use_chinese_function_words():
    assert "柱状图" in build_rag_query("Bar")
    assert "折线图" in build_rag_query("Line")
    assert "饼图" in build_rag_query("Pie")
    assert "网格布局" in build_rag_query("Grid")
    assert "热力图" in build_rag_query("HeatMap")
    assert "散点图" in build_rag_query("EffectScatter")


def test_unknown_chart_type_keeps_type_name():
    query = build_rag_query("Polar")
    assert "Polar" in query
    assert "示例" in query


def test_query_uses_chart_type_and_ignores_business_title():
    retriever = _FakeRetriever([SimpleNamespace(page_content="doc")])

    text = retrieve_reference_docs(
        retriever, {"chart_type": "Line", "chart_title": "2024 年销售额趋势"}
    )

    assert text == "doc"
    assert retriever.queries
    query = retriever.queries[0]
    assert "折线图" in query and "Line" in query
    assert "2024 年销售额趋势" not in query


def test_docs_are_joined_and_none_retriever_is_safe():
    assert retrieve_reference_docs(None, {"chart_type": "Bar"}) == ""

    retriever = _FakeRetriever(
        [SimpleNamespace(page_content="a"), SimpleNamespace(page_content="b")]
    )
    assert retrieve_reference_docs(retriever, {"chart_type": "Bar"}) == "a\n\n---\n\nb"


def test_empty_result_and_errors_return_empty_string():
    empty = _FakeRetriever([])
    assert retrieve_reference_docs(empty, {"chart_type": "Bar"}) == ""

    broken = _FakeRetriever(error=RuntimeError("boom"))
    assert retrieve_reference_docs(broken, {"chart_type": "Bar"}) == ""
