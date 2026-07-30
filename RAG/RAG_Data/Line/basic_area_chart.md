---
图表类型: 折线图 (Line)
功能标签: [面积图, 趋势展示, 填充效果]
数据量级标签: small, medium
适用场景: 展示数据趋势的同时强调数据总量，如销售数据、流量数据等。
数据适应: 适合单系列数据，需要强调数据趋势和总量。
美观要点: 合适的填充色透明度、紧贴Y轴边界、清晰的趋势线。
---

### 基础面积图

这段代码展示了如何创建一个基础的面积图，用于展示数据趋势并强调数据总量。

#### 代码
```python
import pyecharts.options as opts
from pyecharts.charts import Line

x_data = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
y_data = [820, 932, 901, 934, 1290, 1330, 1320]

(
    Line()
    .add_xaxis(xaxis_data=x_data)
    .add_yaxis(
        series_name="",
        y_axis=y_data,
        symbol="emptyCircle",
        is_symbol_show=True,
        label_opts=opts.LabelOpts(is_show=False),
        areastyle_opts=opts.AreaStyleOpts(opacity=1, color="#C67570"),
    )
    .set_global_opts(
        tooltip_opts=opts.TooltipOpts(is_show=False),
        yaxis_opts=opts.AxisOpts(
            type_="value",
            axistick_opts=opts.AxisTickOpts(is_show=True),
            splitline_opts=opts.SplitLineOpts(is_show=True),
        ),
        xaxis_opts=opts.AxisOpts(type_="category", boundary_gap=False),
    )
    .render("basic_area_chart.html")
)
```
