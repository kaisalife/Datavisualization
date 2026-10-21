"""数据驱动的图表类型推荐与 plan 多样性回归（无 LLM）。"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from service.data_ingestion.series.models import SemanticSeries, SeriesCatalog
from service.data_ingestion.series.shape import compute_series_shape
from service.pipeline.chart_recommend import (
    chart_family,
    diversify_plans,
    explicit_chart_types,
    normalize_chart_type,
    recommend_chart_types,
    requested_chart_count,
    requested_styles,
)
from service.pipeline.plan_recipe_tools import ListSeriesTool
from service.pipeline.plan_validator import validate_plans

pytestmark = pytest.mark.whitebox


def _series(
    tmp_path: Path,
    df: pd.DataFrame,
    axis_kind: str,
    row: str | None,
    columns: list[str],
    series_id: str,
) -> SemanticSeries:
    path = tmp_path / f"{series_id.replace('.', '_')}.parquet"
    df.to_parquet(path, index=False)
    shape = compute_series_shape(df, axis_kind, row, columns)
    return SemanticSeries(
        series_id=series_id,
        name=series_id,
        axis_kind=axis_kind,
        row_label_column=row,
        column_label_columns=columns,
        data_path=str(path),
        source_table="t",
        description="测试系列",
        extra_semantics={"shape": shape},
    )


@pytest.fixture
def time_series(tmp_path: Path) -> SemanticSeries:
    df = pd.DataFrame({
        "月份": [f"{m}月" for m in range(1, 13)],
        "销售额": [100 + m * 10 for m in range(12)],
        "利润": [10 + m for m in range(12)],
    })
    return _series(tmp_path, df, "time_series", "月份", ["销售额", "利润"], "sales.月度")


@pytest.fixture
def short_time_series(tmp_path: Path) -> SemanticSeries:
    """只有两个时间点的宽表（年份 × 地区）。"""
    df = pd.DataFrame({
        "年份": ["2024", "2025"],
        "华东": [1100.0, 1234.5],
        "华南": [870.5, 980.0],
    })
    return _series(
        tmp_path, df, "time_series", "年份", ["华东", "华南"], "sales.年份"
    )


@pytest.fixture
def category_series(tmp_path: Path) -> SemanticSeries:
    df = pd.DataFrame({
        "城市": ["北京", "上海", "广州", "深圳"],
        "2024年": [980, 870, 760, 620],
    })
    return _series(
        tmp_path, df, "categorical_comparison", "城市", ["2024年"], "sales.城市"
    )


@pytest.fixture
def many_category_series(tmp_path: Path) -> SemanticSeries:
    """10 个非负类别：柱状图之后可补矩形树图看构成。"""
    df = pd.DataFrame({
        "城市": [f"城市{i}" for i in range(1, 11)],
        "销售额": [980, 870, 760, 620, 580, 540, 510, 480, 450, 420],
    })
    return _series(
        tmp_path, df, "categorical_comparison", "城市", ["销售额"], "sales.多城市"
    )


@pytest.fixture
def numeric_distribution_series(tmp_path: Path) -> SemanticSeries:
    """没有行标签的单列数值：应看分布，而不是当成类别柱状图。"""
    df = pd.DataFrame({
        "销售额": [98, 102, 97, 105, 110, 99, 101, 108, 95, 112,
                  100, 104, 96, 107, 103, 109, 94, 111, 106, 113],
    })
    return _series(
        tmp_path, df, "generic", None, ["销售额"], "sales.单列数值"
    )


@pytest.fixture
def negative_series(tmp_path: Path) -> SemanticSeries:
    df = pd.DataFrame({
        "城市": ["北京", "上海", "广州"],
        "利润": [120, -30, 80],
    })
    return _series(
        tmp_path, df, "categorical_comparison", "城市", ["利润"], "sales.亏损"
    )


def _catalog(tmp_path: Path, *series: SemanticSeries) -> SeriesCatalog:
    return SeriesCatalog(datasets_dir=str(tmp_path), series=list(series))


def _plan(plan_id: str, chart_type: str, series_id: str, x: str, y: list[str],
          title: str, reason: str = "") -> dict:
    return {
        "plan_id": plan_id,
        "plan_name": title,
        "chart_type": chart_type,
        "chart_title": title,
        "chart_reason": reason or title,
        "series_id": series_id,
        "transform_hint": "",
        "x_axis": x,
        "y_axis": y,
        "use_column_names": True,
        "execution_order": int(plan_id),
        "layout": {"legend_pos": "bottom", "grid_top": "10%", "grid_bottom": "12%"},
    }


def test_explicit_chart_types_and_count():
    assert explicit_chart_types("画两个柱状图和折线图") == ["bar", "line"]
    assert explicit_chart_types("用饼图看占比") == ["pie"]
    assert requested_chart_count("画两个图") == 2
    assert requested_chart_count("生成 3 张图表") == 3
    assert requested_chart_count("一张图里包含多个表") is None
    assert requested_styles("各年份趋势 + 各区域对比") == ["trend", "comparison"]


def test_time_series_recommends_line(time_series: SemanticSeries):
    advice = recommend_chart_types(time_series, "分析销售趋势")
    assert advice["recommended"][0] == "Line"
    assert "Area" in advice["recommended"]
    assert "12 个时间点" in advice["shape_summary"]


def test_explicit_bar_wins_over_time_series_default(time_series: SemanticSeries):
    advice = recommend_chart_types(time_series, "画柱状图看各月销售额")
    assert advice["recommended"][0] == "Bar"


def test_composition_intent_prefers_pie(category_series: SemanticSeries):
    advice = recommend_chart_types(category_series, "看各城市销售额占比")
    assert advice["recommended"][0] == "Pie"


def test_negative_values_never_recommend_pie(negative_series: SemanticSeries):
    advice = recommend_chart_types(negative_series, "看利润占比")
    assert "Pie" not in advice["recommended"]
    assert advice["recommended"][0] in {"Treemap", "Bar"}


def test_time_series_bars_are_converted_to_trend(
    tmp_path: Path, time_series: SemanticSeries
):
    catalog = _catalog(tmp_path, time_series)
    plans = [
        _plan("1", "Bar", time_series.series_id, "月份", ["销售额"], "各月份销售额柱状图"),
        _plan("2", "Bar", time_series.series_id, "月份", ["销售额"], "各月份销售额排名", "排名"),
        _plan("3", "Bar", time_series.series_id, "月份", ["利润"], "各月份利润柱状图"),
    ]

    logs: list[str] = []
    result = diversify_plans(plans, catalog, "分析一下销售数据", logs)

    assert any(chart_family(plan["chart_type"]) == "trend" for plan in result)
    assert any(normalize_chart_type(plan["chart_type"]) in {"line", "area"} for plan in result)
    assert len(result) <= 4
    assert [plan["plan_id"] for plan in result] == [str(i) for i in range(1, len(result) + 1)]
    assert any("图表类型按数据形态优化" in line for line in logs)


def test_explicit_bar_only_is_not_auto_converted(
    tmp_path: Path, time_series: SemanticSeries
):
    catalog = _catalog(tmp_path, time_series)
    plans = [
        _plan("1", "Bar", time_series.series_id, "月份", ["销售额"], "各月份销售额柱状图"),
        _plan("2", "Bar", time_series.series_id, "月份", ["利润"], "各月份利润柱状图"),
    ]

    result = diversify_plans(plans, catalog, "只画柱状图看各月销售额")

    assert len(result) == 1
    assert normalize_chart_type(result[0]["chart_type"]) == "bar"


def test_requested_chart_count_is_hard_cap(
    tmp_path: Path, time_series: SemanticSeries
):
    catalog = _catalog(tmp_path, time_series)
    plans = [
        _plan("1", "Bar", time_series.series_id, "月份", ["销售额"], "各月份销售额柱状图"),
        _plan("2", "Bar", time_series.series_id, "月份", ["销售额"], "销售额排名", "排名"),
        _plan("3", "Bar", time_series.series_id, "月份", ["利润"], "各月份利润柱状图"),
        _plan("4", "Pie", time_series.series_id, "月份", ["销售额"], "各月份销售额占比"),
    ]

    result = diversify_plans(
        plans, catalog, "画两个图：各月份销售额趋势和对比"
    )

    assert len(result) == 2
    families = {chart_family(plan["chart_type"]) for plan in result}
    assert families == {"trend", "comparison"}


def test_requested_trend_works_with_two_time_points(
    tmp_path: Path, short_time_series: SemanticSeries
):
    """用户明确要趋势时，2 个时间点也允许补一张折线图（自动补角度仍要求 ≥3 点）。"""
    catalog = _catalog(tmp_path, short_time_series)
    plans = [
        _plan("1", "Bar", short_time_series.series_id, "年份", ["华东"], "各年份华东销售额柱状图"),
    ]

    result = diversify_plans(plans, catalog, "画两个图：各年份销售额趋势和对比")

    assert len(result) == 2
    assert any(chart_family(plan["chart_type"]) == "trend" for plan in result)
    assert any(chart_family(plan["chart_type"]) == "comparison" for plan in result)


def test_existing_relationship_plan_is_preserved(tmp_path: Path):
    """LLM 已画出 Bar+Scatter 时，不能为了补"构成"把散点图硬改成饼图。"""
    df = pd.DataFrame({
        "城市": ["北京", "上海", "广州", "深圳"],
        "销售额": [980, 870, 760, 620],
        "利润": [120, 95, 80, 65],
    })
    series = _series(
        tmp_path, df, "categorical_comparison", "城市", ["销售额", "利润"], "sales.城市双指标"
    )
    catalog = _catalog(tmp_path, series)
    plans = [
        _plan("1", "Bar", series.series_id, "城市", ["销售额", "利润"], "各城市销售额与利润对比"),
        _plan("2", "Scatter", series.series_id, "销售额", ["利润"], "销售额与利润关系"),
    ]

    result = diversify_plans(plans, catalog, "画两个图，分析各城市销售表现")

    families = {chart_family(plan["chart_type"]) for plan in result}
    assert len(result) == 2
    assert families == {"comparison", "relationship"}
    assert all(normalize_chart_type(plan["chart_type"]) != "pie" for plan in result)


def test_generic_single_numeric_recommends_distribution(
    numeric_distribution_series: SemanticSeries,
):
    advice = recommend_chart_types(numeric_distribution_series, "分析一下销售数据")

    assert advice["recommended"][0] == "Histogram"
    assert "Boxplot" in advice["recommended"]
    assert "分布" in advice["reason"]


def test_generic_single_numeric_gains_distribution_plan(
    tmp_path: Path, numeric_distribution_series: SemanticSeries
):
    catalog = _catalog(tmp_path, numeric_distribution_series)
    plans = [
        _plan(
            "1",
            "Bar",
            numeric_distribution_series.series_id,
            "销售额",
            ["销售额"],
            "销售额柱状图",
        ),
    ]

    result = diversify_plans(plans, catalog, "分析一下销售数据")

    assert len(result) == 2
    assert any(chart_family(plan["chart_type"]) == "comparison" for plan in result)
    assert any(chart_family(plan["chart_type"]) == "distribution" for plan in result)
    assert any(
        normalize_chart_type(plan["chart_type"]) in {"histogram", "boxplot"}
        for plan in result
    )


def test_many_categories_recommend_treemap_for_composition(
    many_category_series: SemanticSeries,
):
    advice = recommend_chart_types(many_category_series, "分析各城市销售额")

    assert advice["recommended"][0] == "Bar"
    assert "Treemap" in advice["alternatives"]


def test_many_categories_gain_treemap_plan(
    tmp_path: Path, many_category_series: SemanticSeries
):
    catalog = _catalog(tmp_path, many_category_series)
    plans = [
        _plan(
            "1",
            "Bar",
            many_category_series.series_id,
            "城市",
            ["销售额"],
            "各城市销售额柱状图",
        ),
        _plan(
            "2",
            "Bar",
            many_category_series.series_id,
            "城市",
            ["销售额"],
            "各城市销售额排名",
            "排名",
        ),
    ]

    result = diversify_plans(plans, catalog, "分析各城市销售额")

    assert len(result) == 2
    assert any(chart_family(plan["chart_type"]) == "comparison" for plan in result)
    composition = [
        plan for plan in result if chart_family(plan["chart_type"]) == "composition"
    ]
    assert composition
    assert normalize_chart_type(composition[0]["chart_type"]) == "treemap"
    assert len(validate_plans(result, catalog, None, [])) == len(result)


def test_categorical_bars_gain_composition(
    tmp_path: Path, category_series: SemanticSeries
):
    catalog = _catalog(tmp_path, category_series)
    plans = [
        _plan("1", "Bar", category_series.series_id, "城市", ["2024年"], "各城市销售额柱状图"),
        _plan("2", "Bar", category_series.series_id, "城市", ["2024年"], "各城市销售额排名", "排名"),
        _plan("3", "Bar", category_series.series_id, "城市", ["2024年"], "各城市销售额柱状图"),
    ]

    result = diversify_plans(plans, catalog, "分析各城市销售额")

    families = [chart_family(plan["chart_type"]) for plan in result]
    assert "comparison" in families
    assert "composition" in families
    assert sum(1 for plan in result if normalize_chart_type(plan["chart_type"]) == "bar") <= 2
    assert len(result) <= 3


def test_diversified_plans_still_pass_validator(
    tmp_path: Path, time_series: SemanticSeries, category_series: SemanticSeries
):
    catalog = _catalog(tmp_path, time_series, category_series)
    plans = [
        _plan("1", "Bar", time_series.series_id, "月份", ["销售额"], "各月份销售额柱状图"),
        _plan("2", "Bar", time_series.series_id, "月份", ["销售额"], "各月份销售额排名", "排名"),
        _plan("3", "Bar", time_series.series_id, "月份", ["利润"], "各月份利润柱状图"),
    ]

    result = diversify_plans(plans, catalog, "分析销售数据")
    validated = validate_plans(result, catalog, None, [])

    assert len(validated) == len(result)


async def test_list_series_tool_reports_shape_and_advice(
    tmp_path: Path, time_series: SemanticSeries
):
    from agent.tools.base import ToolContext

    catalog = _catalog(tmp_path, time_series)
    tool = ListSeriesTool(catalog)

    output = await tool.call({}, ToolContext(auto_confirm=True))

    assert output.success is True
    assert "12 个时间点" in output.output
    assert "建议 Line/Area" in output.output
