---
图表类型: 自定义范围折线图 (Custom Line Range)
功能标签: [范围展示, 折线图, 自定义图表, 区域填充, 混合图表]
数据量级标签: small
适用场景: 展示每个类别的数据范围，同时在范围内绘制一条折线，如温度范围和平均温度等。
数据适应: 类别数量 5-20 之间效果最佳，每个类别有最小值和最大值两个数据点。
美观要点: 范围区域填充颜色清晰，折线平滑，颜色区分明确，范围和折线结合展示。
---

# 自定义范围折线图 (Custom Line Range)

展示数据范围和折线结合的自定义图表，范围区域用区域填充，同时在范围内绘制折线。

## 示例代码

```python
import random

from pyecharts import options as opts
from pyecharts.charts import Custom
from pyecharts.commons.utils import JsCode
from pyecharts.globals import ChartType


data = [
    [0, 26.7, 32.5],
    [1, 25.3, 32.4],
    [2, 24.6, 32.7],
    [3, 26.8, 35.8],
    [4, 26.2, 33.1],
    [5, 24.9, 31.4],
    [6, 25.3, 32.9],
]

x_data = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

line_data = []
for item in data:
    ratio = random.random() * 0.5 + 0.25
    value = item[1] * ratio + item[2] * (1 - ratio)
    line_data.append(value)

c = (
    Custom()
    .register_echarts_x(chart_type=ChartType.LINE_RANGE)
    .add_xaxis(xaxis_data=x_data)
    .add(
        series_name="line",
        render_item=ChartType.LINE_RANGE,
        data=data,
        item_payload_opts={
            "areaStyle": {},
        },
        encode={
            "x": 0,
            "y": [1, 2],
            "tooltip": [1, 2],
        }
    )
    .add(
        series_name="line",
        type_=ChartType.LINE,
        render_item=None,
        data=line_data,
    )
    .set_global_opts(
        xaxis_opts=opts.AxisOpts(type_="category"),
        yaxis_opts=opts.AxisOpts(type_="value"),
        tooltip_opts=opts.TooltipOpts(is_show=True),
        legend_opts=opts.LegendOpts(pos_top=15),
    )
    .render("custom_line_range.html")
)
```
