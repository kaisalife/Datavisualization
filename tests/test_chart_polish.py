"""图表视觉后处理回归（无需 LLM）。

覆盖：默认配色/标题/图例避让、柱宽、标签位置与自动隐藏、千分位、
饼图半径、长类目旋转、Grid 多图、显式配置保留、渲染链路。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from pyecharts import options as opts
from pyecharts.charts import Bar, Boxplot, Grid, Line, Pie, Scatter, TreeMap

from service.pipeline.chart_polish import PALETTE, polish_options
from service.pipeline.chart_sandbox import execute_chart_code

pytestmark = pytest.mark.whitebox


def _dict(value):
    """把 pyecharts BasicOpts / dict 统一成 dict（测试辅助）。"""
    if isinstance(value, dict):
        return value
    raw = getattr(value, "opts", None)
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list) and raw and isinstance(raw[0], dict):
        return raw[0]
    return None


def _label(series):
    return _dict(series.get("label"))


def test_bar_defaults_are_polished():
    chart = (
        Bar()
        .add_xaxis(["北京", "上海", "广州", "深圳"])
        .add_yaxis("销售额", [1200, 1500, 900, 1100])
        .set_global_opts(
            title_opts=opts.TitleOpts(title="各城市销售额"),
            yaxis_opts=opts.AxisOpts(name="销售额（万元）"),
        )
    )
    polish_options(chart.options, width=900)

    series = chart.options["series"][0]
    assert chart.options["color"] == PALETTE
    assert series["barMaxWidth"] == 42

    label = _label(series)
    assert label["show"] is True
    assert label["position"] == "top"
    assert label["color"] == "#334155"

    # 默认顶部居中的图例与标题会重叠，应被移到下方
    legend = chart.options["legend"][0]
    assert legend["bottom"] == "2%"
    assert legend["top"] is None

    grid = chart.options["grid"][0]
    assert grid["containLabel"] is True
    assert grid["top"] == "13%"  # 有标题、无顶部图例
    assert grid["bottom"] == "14%"

    tooltip = _dict(chart.options["tooltip"])
    assert tooltip["trigger"] == "axis"
    assert tooltip["axisPointer"]["type"] == "shadow"

    dumped = chart.dump_options()
    assert "toLocaleString" in dumped
    assert "#4E79A7" in dumped


def test_x_axis_name_is_centered_and_not_clipped():
    """x 轴名称不能贴着轴末端画，否则长名称会在右侧被裁掉。"""
    chart = (
        Bar()
        .add_xaxis(["北京", "上海", "广州", "深圳"])
        .add_yaxis("销售额", [1200, 1500, 900, 1100])
        .set_global_opts(
            title_opts=opts.TitleOpts(title="各城市销售额"),
            xaxis_opts=opts.AxisOpts(name="城市"),
            yaxis_opts=opts.AxisOpts(name="销售额（万元）"),
        )
    )
    polish_options(chart.options, width=900)

    x_axis = _dict(chart.options["xAxis"][0])
    assert x_axis["nameLocation"] == "middle"
    assert x_axis["nameGap"] >= 30
    assert chart.options["grid"][0]["bottom"] == "16%"


def test_rotated_x_labels_reserve_space_for_axis_name():
    """旋转标签 + 轴名时需要更大的底部边距和 nameGap。"""
    categories = [f"2023年第{i}季度" for i in range(1, 9)]
    chart = (
        Bar()
        .add_xaxis(categories)
        .add_yaxis("销售额", list(range(8)))
        .set_global_opts(xaxis_opts=opts.AxisOpts(name="季度"))
    )
    polish_options(chart.options, width=600)

    x_axis = _dict(chart.options["xAxis"][0])
    assert _dict(x_axis["axisLabel"])["rotate"] in (30, 45, 60)
    assert x_axis["nameLocation"] == "middle"
    assert x_axis["nameGap"] >= 60
    assert chart.options["grid"][0]["bottom"] == "20%"


def test_horizontal_bar_labels_are_on_the_right():
    chart = (
        Bar()
        .add_xaxis(["北京", "上海"])
        .add_yaxis("销售额", [1200, 1500])
        .reversal_axis()
        .set_global_opts(title_opts=opts.TitleOpts(title="城市销售"))
    )
    polish_options(chart.options, width=900)
    assert _label(chart.options["series"][0])["position"] == "right"


def test_line_value_axis_scales_to_data_range():
    chart = (
        Line()
        .add_xaxis(["00:00", "00:01", "00:02"])
        .add_yaxis("温度", [70.1, 70.3, 70.2])
        .set_global_opts(yaxis_opts=opts.AxisOpts(type_="value", name="温度（℃）"))
    )
    polish_options(chart.options, width=900)

    y_axis = _dict(chart.options["yAxis"][0])
    assert y_axis["scale"] is True


def test_bar_and_area_keep_zero_baseline():
    bar = (
        Bar()
        .add_xaxis(["A", "B"])
        .add_yaxis("销量", [10, 12])
        .set_global_opts(yaxis_opts=opts.AxisOpts(type_="value"))
    )
    polish_options(bar.options, width=900)
    assert _dict(bar.options["yAxis"][0]).get("scale") is not True

    area = (
        Line()
        .add_xaxis(["A", "B"])
        .add_yaxis("销量", [10, 12], areastyle_opts=opts.AreaStyleOpts(opacity=0.12))
        .set_global_opts(yaxis_opts=opts.AxisOpts(type_="value"))
    )
    polish_options(area.options, width=900)
    assert _dict(area.options["yAxis"][0]).get("scale") is not True


def test_mixed_area_fill_on_multi_line_is_removed():
    chart = (
        Line()
        .add_xaxis(["A", "B", "C"])
        .add_yaxis(
            "设备A", [70, 72, 74],
            areastyle_opts=opts.AreaStyleOpts(opacity=0.12),
        )
        .add_yaxis("设备B", [65, 66, 68])
        .set_global_opts(yaxis_opts=opts.AxisOpts(type_="value"))
    )
    polish_options(chart.options, width=900)

    first = _dict(chart.options["series"][0]).get("areaStyle") or {}
    second = _dict(chart.options["series"][1]).get("areaStyle") or {}
    assert _dict(first).get("opacity") == 0
    assert _dict(second).get("opacity", 0) == 0
    # 去掉填充后是纯折线，数值轴应贴合 65–74，而不是从 0 开始
    assert _dict(chart.options["yAxis"][0])["scale"] is True


def test_line_with_many_points_hides_symbols_and_labels():
    chart = Line().add_xaxis([str(i) for i in range(40)]).add_yaxis(
        "访问量", [i * 10 for i in range(40)]
    )
    polish_options(chart.options, width=900)

    series = chart.options["series"][0]
    assert series["showSymbol"] is False
    assert _label(series)["show"] is False


def test_flat_treemap_hides_breadcrumb_upper_label_and_legend():
    chart = (
        TreeMap()
        .add(
            "销售额（元）",
            [
                {"value": 980, "name": "北京"},
                {"value": 870, "name": "上海"},
                {"value": 760, "name": "广州"},
            ],
        )
        .set_global_opts(
            title_opts=opts.TitleOpts(
                title="各城市销售额构成",
                subtitle="矩形面积与销售额成正比",
            ),
            legend_opts=opts.LegendOpts(pos_bottom="2%"),
        )
    )
    polish_options(chart.options, width=900)

    series = chart.options["series"][0]
    assert series["top"] == "14%"
    assert series["bottom"] == "4%"
    assert _dict(series["breadcrumb"])["show"] is False
    assert _dict(series["upperLabel"])["show"] is False
    assert chart.options["legend"][0]["show"] is False

    label = _label(series)
    assert label["fontFamily"]
    assert label["color"] == "#1f2937"
    assert label["textBorderWidth"] == 2
    assert label["textBorderColor"].startswith("rgba(255")


def test_treemap_preserves_explicit_white_label_with_dark_outline():
    chart = TreeMap().add(
        "销售额",
        [{"value": 980, "name": "北京"}, {"value": 870, "name": "上海"}],
        label_opts=opts.LabelOpts(color="#fff"),
    )
    polish_options(chart.options, width=900)

    label = _label(chart.options["series"][0])
    assert label["color"] == "#fff"
    assert label["textBorderColor"].startswith("rgba(15")


def test_hierarchical_treemap_keeps_breadcrumb():
    chart = TreeMap().add(
        "文件大小",
        [
            {"value": 40, "name": "A"},
            {
                "value": 180,
                "name": "B",
                "children": [
                    {"value": 76, "name": "B-1"},
                    {"value": 104, "name": "B-2"},
                ],
            },
        ],
    )
    polish_options(chart.options, width=900)

    series = chart.options["series"][0]
    breadcrumb = _dict(series.get("breadcrumb"))
    assert breadcrumb is None or breadcrumb.get("show") is not False


def test_pie_uses_safe_radius_and_label_template():
    chart = (
        Pie()
        .add("", [("A", 30), ("B", 20), ("C", 50)])
        .set_global_opts(title_opts=opts.TitleOpts(title="销售额占比"))
    )
    polish_options(chart.options, width=900)

    series = chart.options["series"][0]
    assert series["radius"] == ["32%", "58%"]
    assert series["center"] == ["50%", "55%"]
    assert series["avoidLabelOverlap"] is True
    label = _label(series)
    assert label["position"] == "outside"
    assert label["formatter"] == "{b}: {d}%"


def test_pie_with_many_slices_hides_labels():
    chart = Pie().add("", [(str(i), i + 1) for i in range(20)])
    polish_options(chart.options, width=900)
    assert _label(chart.options["series"][0])["show"] is False


def test_long_category_labels_rotate():
    categories = [
        "北京市朝阳区",
        "上海市浦东新区",
        "广州市天河区",
        "深圳市南山区",
        "杭州市西湖区",
        "成都市高新区",
        "武汉市洪山区",
        "南京市鼓楼区",
    ]
    chart = Bar().add_xaxis(categories).add_yaxis("销售额", list(range(8)))
    polish_options(chart.options, width=600)

    label_opts = _dict(chart.options["xAxis"][0]["axisLabel"])
    assert label_opts["rotate"] in (30, 45, 60)
    assert label_opts.get("interval") == 0


def test_horizontal_long_category_labels_are_truncated_not_rotated():
    chart = (
        Bar()
        .add_xaxis(["北京市朝阳区某某街道", "上海市浦东新区某某街道"])
        .add_yaxis("销售额", [1, 2])
        .reversal_axis()
    )
    polish_options(chart.options, width=900)

    label_opts = _dict(chart.options["yAxis"][0]["axisLabel"])
    assert label_opts["width"] == 140
    assert label_opts["overflow"] == "truncate"
    assert label_opts.get("rotate") is None


def test_stacked_bars_put_labels_inside():
    chart = (
        Bar()
        .add_xaxis(["A", "B"])
        .add_yaxis("线上", [1, 2], stack="渠道", label_opts=opts.LabelOpts(is_show=True))
        .add_yaxis("线下", [2, 3], stack="渠道", label_opts=opts.LabelOpts(is_show=True))
    )
    polish_options(chart.options, width=900)
    assert [_label(series)["position"] for series in chart.options["series"]] == [
        "inside",
        "inside",
    ]


def test_explicit_user_style_is_preserved():
    chart = (
        Bar()
        .add_xaxis(["A", "B"])
        .add_yaxis(
            "销售额",
            [1, 2],
            label_opts=opts.LabelOpts(is_show=True, position="inside"),
        )
        .set_colors(["#111111"])
        .set_global_opts(
            title_opts=opts.TitleOpts(title="标题"),
            tooltip_opts=opts.TooltipOpts(trigger="item", formatter="{b}: {c}"),
        )
    )
    polish_options(chart.options, width=900)

    assert chart.options["color"] == ["#111111"]
    assert _label(chart.options["series"][0])["position"] == "inside"
    assert _dict(chart.options["tooltip"])["trigger"] == "item"


def test_legend_moves_only_when_it_would_overlap_title():
    short = (
        Bar()
        .add_xaxis(["A"])
        .add_yaxis("销售", [1])
        .set_global_opts(
            title_opts=opts.TitleOpts(title="销售"),
            legend_opts=opts.LegendOpts(pos_top="2%", pos_right="3%"),
        )
    )
    polish_options(short.options, width=900)
    assert short.options["legend"][0].get("bottom") is None

    long = (
        Bar()
        .add_xaxis(["A"])
        .add_yaxis("销售额", [1])
        .set_global_opts(
            title_opts=opts.TitleOpts(
                title="二〇二四年全国各城市销售额对比分析报告（含线上、线下、批发、零售全部渠道）"
            ),
            legend_opts=opts.LegendOpts(pos_top="2%", pos_right="3%"),
        )
    )
    polish_options(long.options, width=900)
    assert long.options["legend"][0]["bottom"] == "2%"


def test_grid_layout_is_not_forced_for_multi_chart():
    top = (
        Bar()
        .add_xaxis(["A", "B"])
        .add_yaxis("销售额", [1, 2])
        .set_global_opts(title_opts=opts.TitleOpts(title="图一", pos_top="2%"))
    )
    bottom = (
        Line()
        .add_xaxis(["A", "B"])
        .add_yaxis("访问量", [2, 3])
        .set_global_opts(title_opts=opts.TitleOpts(title="图二", pos_top="55%"))
    )
    grid = (
        Grid()
        .add(top, grid_opts=opts.GridOpts(pos_top="12%"))
        .add(bottom, grid_opts=opts.GridOpts(pos_top="60%"))
    )
    polish_options(grid.options, width=900)

    grids = [_dict(item) for item in grid.options["grid"]]
    assert [item["top"] for item in grids] == ["12%", "60%"]
    assert all(item["containLabel"] is True for item in grids)
    assert grid.options["legend"][0].get("bottom") is None


def test_overlay_grid_merges_duplicate_axes_and_legend():
    values = [98, 102, 97, 105, 110, 99, 101, 108]
    box = (
        Boxplot()
        .add_xaxis(["销售额"])
        .add_yaxis("销售额", Boxplot.prepare_data([[94, 97, 102, 108, 113]]))
    )
    scatter = (
        Scatter()
        .add_xaxis(["销售额"] * len(values))
        .add_yaxis("观测值", values)
    )
    grid_opts = opts.GridOpts(
        pos_top="12%", pos_bottom="18%", pos_left="8%", pos_right="5%"
    )
    chart = Grid().add(box, grid_opts=grid_opts).add(scatter, grid_opts=grid_opts)
    polish_options(chart.options, width=900)

    series = chart.options["series"]
    assert series[1]["xAxisIndex"] == 0
    assert series[1]["yAxisIndex"] == 0
    assert _dict(chart.options["xAxis"][1])["show"] is False
    assert _dict(chart.options["yAxis"][1])["show"] is False

    legends = [_dict(item) for item in chart.options["legend"]]
    assert legends[0]["show"] is True
    assert legends[0]["data"] == ["销售额", "观测值"]
    assert legends[1]["show"] is False


def test_non_overlay_grid_keeps_separate_axes():
    top = Bar().add_xaxis(["A", "B"]).add_yaxis("销售额", [1, 2])
    bottom = Line().add_xaxis(["A", "B"]).add_yaxis("访问量", [2, 3])
    chart = (
        Grid()
        .add(top, grid_opts=opts.GridOpts(pos_top="12%", pos_bottom="55%"))
        .add(bottom, grid_opts=opts.GridOpts(pos_top="58%", pos_bottom="12%"))
    )
    polish_options(chart.options, width=900)

    assert chart.options["series"][1]["xAxisIndex"] == 1
    assert chart.options["series"][1]["yAxisIndex"] == 1
    assert _dict(chart.options["xAxis"][1])["show"] is not False


def test_polish_is_idempotent():
    chart = (
        Bar()
        .add_xaxis(["A", "B"])
        .add_yaxis("销售额", [1, 2])
        .set_global_opts(title_opts=opts.TitleOpts(title="销售"))
    )
    polish_options(chart.options, width=900)
    first = chart.dump_options()
    polish_options(chart.options, width=900)
    assert chart.dump_options() == first


def test_bar_hides_zero_value_labels():
    chart = Bar().add_xaxis(["A", "B", "C"]).add_yaxis("频数", [0, 5, 0])
    polish_options(chart.options, width=900)

    formatter = _label(chart.options["series"][0])["formatter"]
    assert "v === 0" in formatter.js_code


def test_dark_theme_uses_light_label_text():
    chart = Bar().add_xaxis(["A"]).add_yaxis("销售额", [1])
    polish_options(chart.options, width=900, dark=True)
    label = _label(chart.options["series"][0])
    assert label["color"] == "#e2e8f0"


def test_render_pipeline_applies_polish(tmp_path: Path):
    code = """
from pyecharts import options as opts
from pyecharts.charts import Bar

chart = (
    Bar()
    .add_xaxis(['北京', '上海', '广州'])
    .add_yaxis('销售额', [1200, 1500, 900])
    .set_global_opts(
        title_opts=opts.TitleOpts(title='各城市销售额'),
        yaxis_opts=opts.AxisOpts(name='销售额（万元）'),
    )
)
chart.render()
"""
    result = execute_chart_code(code, charts_folder=tmp_path, plan_id="polish")
    assert result.success, result.output
    html = Path(result.chart_path).read_text(encoding="utf-8")
    for token in (
        "#4E79A7",
        '"barMaxWidth": 42',
        '"position": "top"',
        '"containLabel": true',
        "toLocaleString",
    ):
        assert token in html
