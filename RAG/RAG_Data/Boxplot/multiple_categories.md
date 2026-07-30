---
图表类型: 箱线图 (Boxplot)
功能标签: [多类别, 自定义数据, JsCode, 数据缩放, 大数据量]
数据量级标签: large, huge
适用场景: 展示多个类别的大量实验数据，如机器学习中的多组实验结果对比。
数据适应: 适合大数据量，多类别对比，需要数据缩放功能的情况。
美观要点: 使用JsCode自定义提示框，添加数据缩放功能，清晰的图例。
---

### 多类别箱线图

这段代码展示了如何创建多类别的箱线图，使用自定义数据格式，并添加数据缩放功能。

#### 代码
```python
import pyecharts.options as opts
from pyecharts.charts import Boxplot
from pyecharts.commons.utils import JsCode

axis_data = [
    "0",
    "1",
    "2",
    "3",
    "4",
    "5",
    "6",
    "7",
    "8",
    "9",
    "10",
    "11",
    "12",
    "13",
    "14",
    "15",
    "16",
    "17",
]

data = [
    {
        "axisData": axis_data,
        "boxData": [
            [
                3.8888578346043534,
                55.82692798765428,
                98.71608835477272,
                149.50917642877687,
                196.31621070646452,
            ],
            # ... (更多箱线数据)
        ],
        "outliers": [],
    },
    # ... (更多类别数据)
]

(
    Boxplot()
    .add_xaxis(xaxis_data=axis_data)
    .add_yaxis(
        series_name="category0",
        y_axis=data[0]["boxData"],
        tooltip_opts=opts.TooltipOpts(
            formatter=JsCode(
                """function(param) { return [
                            'Experiment ' + param.name + ': ',
                            'upper: ' + param.data[0],
                            'Q1: ' + param.data[1],
                            'median: ' + param.data[2],
                            'Q3: ' + param.data[3],
                            'lower: ' + param.data[4]
                        ].join('<br/>') }"""
            )
        ),
    )
    .add_yaxis(
        series_name="category1",
        y_axis=data[1]["boxData"],
        tooltip_opts=opts.TooltipOpts(
            formatter=JsCode(
                """function(param) { return [
                            'Experiment ' + param.name + ': ',
                            'upper: ' + param.data[0],
                            'Q1: ' + param.data[1],
                            'median: ' + param.data[2],
                            'Q3: ' + param.data[3],
                            'lower: ' + param.data[4]
                        ].join('<br/>') }"""
            )
        ),
    )
    .add_yaxis(
        series_name="category2",
        y_axis=data[2]["boxData"],
        tooltip_opts=opts.TooltipOpts(
            formatter=JsCode(
                """function(param) { return [
                            'Experiment ' + param.name + ': ',
                            'upper: ' + param.data[0],
                            'Q1: ' + param.data[1],
                            'median: ' + param.data[2],
                            'Q3: ' + param.data[3],
                            'lower: ' + param.data[4]
                        ].join('<br/>') }"""
            )
        ),
    )
    .set_global_opts(
        title_opts=opts.TitleOpts(title="Multiple Categories", pos_left="center"),
        legend_opts=opts.LegendOpts(pos_top="3%"),
        tooltip_opts=opts.TooltipOpts(trigger="item", axis_pointer_type="shadow"),
        xaxis_opts=opts.AxisOpts(
            name_gap=30,
            boundary_gap=True,
            splitarea_opts=opts.SplitAreaOpts(
                areastyle_opts=opts.AreaStyleOpts(opacity=1)
            ),
            axislabel_opts=opts.LabelOpts(formatter="expr {value}"),
            splitline_opts=opts.SplitLineOpts(is_show=False),
        ),
        yaxis_opts=opts.AxisOpts(
            type_="value",
            min_=-400,
            max_=600,
            splitarea_opts=opts.SplitAreaOpts(is_show=False),
        ),
        datazoom_opts=[
            opts.DataZoomOpts(type_="inside", range_start=0, range_end=20),
            opts.DataZoomOpts(type_="slider", xaxis_index=0, is_show=True),
        ],
    )
    .render("multiple_categories.html")
)
```
