---
图表类型: 仪表盘 (Gauge)
功能标签: [仪表盘, 自定义颜色, 颜色渐变]
数据量级标签: small
适用场景: 需要自定义仪表盘颜色的场景。
数据适应: 适合展示单个百分比数据。
美观要点: 自定义颜色、颜色渐变、清晰的刻度。
---

### 自定义颜色仪表盘

这段代码展示了如何创建自定义颜色的仪表盘。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Gauge

c = (
    Gauge()
    .add(
        "业务指标",
        [("完成率", 55.5)],
        axisline_opts=opts.AxisLineOpts(
            linestyle_opts=opts.LineStyleOpts(
                color=[(0.3, "#67e0e3"), (0.7, "#37a2da"), (1, "#fd666d")], width=30
            )
        ),
    )
    .set_global_opts(
        title_opts=opts.TitleOpts(title="Gauge-不同颜色"),
        legend_opts=opts.LegendOpts(is_show=False),
    )
    .render("gauge_color.html")
)
```
