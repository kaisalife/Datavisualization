---
图表类型: 柱状图 (Bar)
功能标签: [瀑布图, 收入, 支出]
数据量级标签: small, medium
适用场景: 展示数据逐步变化过程。
数据适应: 适合展示财务数据的收支变化、项目进度等逐步变化的数据。
美观要点: 清晰的瀑布效果、收支对比明显。
---

### 瀑布图

这段代码展示了如何创建瀑布图，用于展示数据的逐步变化过程，特别适合财务收支分析。

#### 代码
```python
from pyecharts.charts import Bar
from pyecharts import options as opts

x_data = [f"11月{str(i)}日" for i in range(1, 12)]
y_total = [0, 900, 1245, 1530, 1376, 1376, 1511, 1689, 1856, 1495, 1292]
y_in = [900, 345, 393, "-", "-", 135, 178, 286, "-", "-", "-"]
y_out = ["-", "-", "-", 108, 154, "-", "-", "-", 119, 361, 203]


bar = (
    Bar()
    .add_xaxis(xaxis_data=x_data)
    .add_yaxis(
        series_name="",
        y_axis=y_total,
        stack="总量",
        itemstyle_opts=opts.ItemStyleOpts(color="rgba(0,0,0,0)"),
    )
    .add_yaxis(series_name="收入", y_axis=y_in, stack="总量")
    .add_yaxis(series_name="支出", y_axis=y_out, stack="总量")
    .set_global_opts(yaxis_opts=opts.AxisOpts(type_="value"))
    .render("bar_waterfall_plot.html")
)
```
