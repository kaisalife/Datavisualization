---
图表类型: 仪表盘 (Gauge)
功能标签: [仪表盘, 分割段数, 自定义标签]
数据量级标签: small
适用场景: 需要自定义仪表盘分割段数和标签格式的场景。
数据适应: 适合展示单个百分比数据。
美观要点: 自定义分割段数、自定义标签格式、清晰的刻度。
---

### 自定义分割段数仪表盘

这段代码展示了如何创建自定义分割段数和标签格式的仪表盘。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Gauge

c = (
    Gauge()
    .add(
        "业务指标",
        [("完成率", 55.5)],
        split_number=5,
        axisline_opts=opts.AxisLineOpts(
            linestyle_opts=opts.LineStyleOpts(
                color=[(0.3, "#67e0e3"), (0.7, "#37a2da"), (1, "#fd666d")], width=30
            )
        ),
        detail_label_opts=opts.LabelOpts(formatter="{value}"),
    )
    .set_global_opts(
        title_opts=opts.TitleOpts(title="Gauge-分割段数-Label"),
        legend_opts=opts.LegendOpts(is_show=False),
    )
    .render("gauge_splitnum_label.html")
)
```
