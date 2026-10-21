"""图表数据检查回归：空数据/全零不能静默成功（无 LLM）。"""
from __future__ import annotations

from pathlib import Path

import pytest

from service.pipeline import generation_validation as gv
from service.pipeline.chart_data_check import (
    chart_data_issues,
    summarize_chart_options,
)
from service.pipeline.chart_sandbox import execute_chart_code

pytestmark = pytest.mark.whitebox


def test_summarize_bar_data_counts_points_and_zeros():
    stats = summarize_chart_options({
        "series": [{
            "type": "bar",
            "name": "销售额",
            "data": [0, 12, None, 8],
        }]
    })

    assert stats["series_count"] == 1
    assert stats["types"] == ["bar"]
    assert stats["total_points"] == 4
    assert stats["empty_points"] == 1
    assert stats["numeric_values"] == 3
    assert stats["zero_values"] == 1
    assert chart_data_issues(stats) == []


def test_pie_and_treemap_dict_values_are_counted():
    pie = summarize_chart_options({
        "series": [{
            "type": "pie",
            "data": [{"name": "北京", "value": 0}, {"name": "上海", "value": 5}],
        }]
    })
    treemap = summarize_chart_options({
        "series": [{
            "type": "treemap",
            "data": [{"name": "北京", "value": 0}, {"name": "上海", "value": 5}],
        }]
    })

    assert pie["total_points"] == 2
    assert pie["numeric_values"] == 2
    assert pie["zero_values"] == 1
    assert treemap["total_points"] == 2
    assert treemap["numeric_values"] == 2


def test_empty_and_all_null_data_are_errors():
    empty = summarize_chart_options({"series": [{"type": "bar", "data": []}]})
    all_null = summarize_chart_options({
        "series": [{"type": "bar", "data": [None, None]}]
    })

    empty_issues = chart_data_issues(empty)
    null_issues = chart_data_issues(all_null)

    assert empty_issues[0]["code"] == "CHART_DATA_EMPTY"
    assert empty_issues[0]["severity"] == "error"
    assert null_issues[0]["code"] == "CHART_DATA_ALL_NULL"
    assert null_issues[0]["severity"] == "error"


def test_all_zero_and_mostly_empty_are_warnings():
    all_zero = summarize_chart_options({
        "series": [{"type": "line", "data": [0, 0, 0]}]
    })
    mostly_empty = summarize_chart_options({
        "series": [{"type": "line", "data": [None, None, 3]}]
    })

    assert chart_data_issues(all_zero)[0]["code"] == "CHART_DATA_ALL_ZERO"
    assert chart_data_issues(all_zero)[0]["severity"] == "warning"
    assert chart_data_issues(mostly_empty)[0]["code"] == "CHART_DATA_MOSTLY_EMPTY"


def test_dataset_charts_are_not_treated_as_empty():
    stats = summarize_chart_options({"dataset": {"source": []}, "series": []})
    assert stats["has_dataset"] is True
    assert chart_data_issues(stats) == []


def test_runtime_report_adds_data_errors_and_warnings(tmp_path: Path):
    html = tmp_path / "chart.html"
    html.write_text("<html><script>echarts.init(el)</script></html>", encoding="utf-8")
    empty = summarize_chart_options({"series": [{"type": "bar", "data": []}]})
    all_zero = summarize_chart_options({
        "series": [{"type": "bar", "data": [0, 0]}]
    })

    empty_report = gv.runtime_report(ok=True, attempt=1, chart_path=html, data_stats=empty)
    zero_report = gv.runtime_report(ok=True, attempt=1, chart_path=html, data_stats=all_zero)

    assert empty_report["ok"] is False
    assert empty_report["errors"][0]["code"] == "CHART_DATA_EMPTY"
    assert empty_report["data"]["total_points"] == 0
    assert zero_report["ok"] is True
    assert zero_report["warnings"][0]["code"] == "CHART_DATA_ALL_ZERO"


def test_sandbox_captures_data_stats(tmp_path: Path):
    code = """
from pyecharts.charts import Bar

chart = Bar()
chart.add_xaxis(["北京", "上海"])
chart.add_yaxis("销售额", [980, 870])
chart.render()
"""
    result = execute_chart_code(code, charts_folder=tmp_path, plan_id="data-check")

    assert result.success is True
    assert result.data_stats is not None
    assert result.data_stats["total_points"] == 2
    assert result.data_stats["types"] == ["bar"]
    assert "__CHART_DATA_STATS__" not in result.output


def test_sandbox_flags_empty_series_as_repairable_error(tmp_path: Path):
    code = """
from pyecharts.charts import Bar

chart = Bar()
chart.add_xaxis([])
chart.add_yaxis("销售额", [])
chart.render()
"""
    result = execute_chart_code(code, charts_folder=tmp_path, plan_id="data-empty")

    assert result.success is True
    assert result.data_stats["total_points"] == 0
    report = gv.runtime_report(
        ok=True,
        attempt=1,
        chart_path=result.chart_path,
        data_stats=result.data_stats,
    )
    assert report["ok"] is False
    assert report["errors"][0]["code"] == "CHART_DATA_EMPTY"
