---
图表类型: 折线图 (Line)
功能标签: [趋势展示, 简洁样式, 网格线]
数据量级标签: small, medium
适用场景: 简洁展示单组数据的时间趋势，如周数据、月度数据等。
数据适应: 适合单系列数据，时间序列数据。
美观要点: 简洁的样式、清晰的网格线、空心圆点数据标记。
---

### 简单折线图

这段代码展示了如何创建一个简洁样式的折线图，用于展示单组数据的趋势。

#### 代码
```python
import pyecharts.options as opts
from pyecharts.charts import Line

x_data = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
y_data = [820, 932, 901, 934, 1290, 1330, 1320]

(
    Line()
    .set_global_opts(
        tooltip_opts=opts.TooltipOpts(is_show=False),
        xaxis_opts=opts.AxisOpts(type_="category"),
        yaxis_opts=opts.AxisOpts(
            type_="value",
            axistick_opts=opts.AxisTickOpts(is_show=True),
            splitline_opts=opts.SplitLineOpts(is_show=True),
        ),
    )
    .add_xaxis(xaxis_data=x_data)
    .add_yaxis(
        series_name="",
        y_axis=y_data,
        symbol="emptyCircle",
        is_symbol_show=True,
        label_opts=opts.LabelOpts(is_show=False),
    )
    .render("basic_line_chart.html")
)
```
