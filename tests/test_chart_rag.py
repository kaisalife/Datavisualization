"""RAG 检索 query 与容错回归（不加载真实模型）。"""
from __future__ import annotations

from types import SimpleNamespace

from service.pipeline.chart_rag import (
    build_rag_query,
    filter_reference_docs,
    infer_doc_chart_type,
    plan_feature_queries,
    retrieve_reference_docs,
)


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
    query = build_rag_query("Violin")
    assert "Violin" in query
    assert "示例" in query


def test_extended_chart_types_use_function_words():
    assert "日历图" in build_rag_query("Calendar")
    assert "K线图" in build_rag_query("Kline")
    assert "旭日图" in build_rag_query("Sunburst")
    assert "象形柱图" in build_rag_query("PictorialBar")
    assert "极坐标系" in build_rag_query("Polar")
    assert "3D 柱状图" in build_rag_query("Bar3D")
    assert "柱线组合" in build_rag_query("Overlap")
    assert "时间轴" in build_rag_query("Timeline")
    assert "数据集" in build_rag_query("Dataset")


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


def test_plan_query_adds_analysis_and_shape_features_without_title():
    query = build_rag_query({
        "chart_type": "Line",
        "chart_title": "2024 年销售额趋势",
        "analysis_task": "trend",
        "y_axis": ["销售额", "利润"],
        "transform_hint": "计算同比增长率",
        "layout": {"legend_pos": "bottom", "grid_top": "8%"},
    })

    assert "折线图" in query and "Line" in query
    assert "趋势" in query
    assert "多系列" in query
    assert "数据变换" in query
    assert "图例" in query
    assert "2024 年销售额趋势" not in query


def test_infer_doc_type_from_metadata_or_source_folder():
    assert infer_doc_chart_type(SimpleNamespace(metadata={"chart_type": "HeatMap"})) == "heatmap"
    assert infer_doc_chart_type(
        SimpleNamespace(metadata={"source": r"D:\kb\RAG_Data\Bar\bar_base.md"})
    ) == "bar"
    assert infer_doc_chart_type(SimpleNamespace(metadata={})) == ""


def test_filter_docs_prefers_matching_chart_type_and_falls_back():
    docs = [
        SimpleNamespace(page_content="bar", metadata={"source": "RAG_Data/Bar/base.md"}),
        SimpleNamespace(page_content="line", metadata={"source": "RAG_Data/Line/base.md"}),
        SimpleNamespace(page_content="bar2", metadata={"source": "RAG_Data/Bar/base.md"}),
    ]

    selected = filter_reference_docs(docs, {"chart_type": "Bar"}, max_docs=4)
    assert [d.page_content for d in selected] == ["bar", "bar2"]

    # 没有匹配项时回退到原始结果，并去重、限流
    fallback = filter_reference_docs(docs, {"chart_type": "Pie"}, max_docs=2)
    assert [d.page_content for d in fallback] == ["bar", "line"]


def test_retrieve_uses_filtered_docs_and_dedupes():
    retriever = _FakeRetriever([
        SimpleNamespace(page_content="line-a", metadata={"source": "RAG_Data/Line/a.md"}),
        SimpleNamespace(page_content="bar", metadata={"source": "RAG_Data/Bar/b.md"}),
        SimpleNamespace(page_content="line-a", metadata={"source": "RAG_Data/Line/a.md"}),
    ])

    text = retrieve_reference_docs(retriever, {"chart_type": "Line"}, max_docs=4)
    assert text == "line-a"
    assert "折线图" in retriever.queries[0]


# ---------- Feature 高级用法文档通道 ----------


class _RoutingRetriever:
    """主 query 与 Feature query 返回不同文档集合。"""

    def __init__(self, main_docs, feature_docs):
        self.main_docs = main_docs
        self.feature_docs = feature_docs
        self.queries: list[str] = []

    def retrieve(self, query: str):
        self.queries.append(query)
        for triggers, feature_query in [
            ({"目标线", "markline"}, "markLine 参考线 目标线 均值线 示例"),
        ]:
            if any(t in query.lower() for t in triggers):
                return self.feature_docs
        return self.main_docs


def test_feature_triggers_scan_plan_text_fields():
    plan = {
        "chart_type": "Line",
        "chart_title": "月度销售额",
        "chart_reason": "对比实际与 2024 目标线",
        "transform_hint": "",
    }

    queries = plan_feature_queries(plan)

    assert queries == ["markLine 参考线 目标线 均值线 示例"]

    # 无触发词时不追加检索
    assert plan_feature_queries({"chart_type": "Bar", "chart_reason": "对比各城市"}) == []


def test_feature_queries_dedupe_and_cap():
    plan = {
        "chart_reason": "标注旺季参考区间并保留长序列滚动浏览，另加目标线",
    }

    queries = plan_feature_queries(plan)

    assert len(queries) == 2  # 上限 2 条
    assert len(queries) == len(set(queries))


def test_feature_docs_appended_after_main_docs():
    retriever = _RoutingRetriever(
        main_docs=[SimpleNamespace(page_content="line-main", metadata={"source": "RAG_Data/Line/a.md"})],
        feature_docs=[
            SimpleNamespace(page_content="markline-doc", metadata={"source": "RAG_Data/Feature/markline.md"}),
            SimpleNamespace(page_content="bar-noise", metadata={"source": "RAG_Data/Bar/b.md"}),
        ],
    )

    text = retrieve_reference_docs(
        retriever, {"chart_type": "Line", "chart_reason": "带目标线"}
    )

    assert text.startswith("line-main")
    assert "markline-doc" in text  # Feature 文档在主文档之后
    assert "bar-noise" not in text  # 非 Feature 文档被过滤
    assert len(retriever.queries) == 2  # 主 query + Feature 补充 query


def test_feature_retrieval_failure_degrades_gracefully():
    class _FailOnSecond:
        def __init__(self):
            self.calls = 0

        def retrieve(self, query):
            self.calls += 1
            if self.calls > 1:
                raise RuntimeError("feature boom")
            return [SimpleNamespace(page_content="line", metadata={"source": "RAG_Data/Line/x.md"})]

    # 主检索正常，Feature 补充检索抛错被吞掉，主文档照常返回
    text = retrieve_reference_docs(_FailOnSecond(), {"chart_type": "Line"})
    assert text == "line"
