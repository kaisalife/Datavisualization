---
图表类型: 自定义范围柱状图 (Custom Bar Range)
功能标签: [范围展示, 柱状图, 自定义图表, 数据范围]
数据量级标签: small
适用场景: 展示每个类别的数据范围，如温度范围、价格区间等。
数据适应: 类别数量 5-20 之间效果最佳，每个类别有最小值和最大值两个数据点。
美观要点: 柱状图有圆角，宽度适中，范围展示清晰，颜色区分明确。
---

# 自定义范围柱状图 (Custom Bar Range)

展示每个类别的数据范围的自定义柱状图。

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


c = (
    Custom()
    .register_echarts_x(chart_type=ChartType.BAR_RANGE)
    .add_xaxis(xaxis_data=x_data)
    .add(
        series_name="bar",
        render_item=ChartType.BAR_RANGE,
        data=data,
        item_payload_opts={
            "barWidth": 10,
            "borderRadius": 5,
        },
        encode={
            "x": 0,
            "y": [1, 2],
            "tooltip": [1, 2],
        }
    )
    .set_global_opts(
        xaxis_opts=opts.AxisOpts(type_="category"),
        yaxis_opts=opts.AxisOpts(type_="value"),
        tooltip_opts=opts.TooltipOpts(is_show=True),
    )
    .render("custom_bar_range.html")
)
```
