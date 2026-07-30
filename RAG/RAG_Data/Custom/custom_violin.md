---
图表类型: 自定义小提琴图 (Custom Violin)
功能标签: [小提琴图, 散点图, 自定义图表, 分布展示, 数据分布]
数据量级标签: medium
适用场景: 展示数据分布情况，如不同类别的数据分布、统计分析等。
数据适应: 类别数量 5-15 之间效果最佳，每个类别有多个数据点。
美观要点: 小提琴图形状美观，区域透明度适中，散点抖动分布合理，颜色区分明确。
---

# 自定义小提琴图 (Custom Violin)

展示数据分布的自定义小提琴图，同时叠加散点图展示原始数据。

## 示例代码

```python
import math
import random

from pyecharts import options as opts
from pyecharts.charts import Custom
from pyecharts.globals import ChartType


x_data = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

data_source = [['Day', 'value']]

for i in range(len(x_data)):
    data_count = 10 * round(random.random() * 5) + 5

    for j in range(data_count):
        value = math.tan(i) / 2 + 3 * random.random() + 2
        data_source.append([x_data[i], value])


c = (
    Custom()
    .register_echarts_x(chart_type=ChartType.VIOLIN)
    .add(
        series_name="violin",
        color_by="item",
        render_item=ChartType.VIOLIN,
        item_payload_opts={
            "symbolSize": 4,
            "areaOpacity": 0.6,
            "bandWidthScale": 1.5,
        },
    )
    .add(
        series_name="scatter",
        type_=ChartType.SCATTER,
        render_item=None,
        encode={"x": 0, "y": 1},
        color_by="item",
    )
    .add_xaxis(xaxis_data=x_data)
    .add_dataset(source=data_source)
    .set_global_opts(
        tooltip_opts=opts.TooltipOpts(is_show=True),
        xaxis_opts={
            "type": "category",
            "jitter": 100,
            "jitterOverlap": False,
        },
        yaxis_opts=None,
        legend_opts={},
    )
    .render("custom_violin.html")
)
```
