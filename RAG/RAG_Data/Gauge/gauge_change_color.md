---
图表类型: 仪表盘 (Gauge)
功能标签: [仪表盘, 颜色渐变, 分段颜色]
数据量级标签: small
适用场景: 根据百分比值显示不同颜色的场景，如绿色表示良好、红色表示警告。
数据适应: 适合展示单个百分比数据。
美观要点: 颜色渐变、分段颜色、清晰的刻度。
---

### 分段颜色仪表盘

这段代码展示了如何创建分段颜色的仪表盘，根据数值范围显示不同颜色。

#### 代码
```python
import pyecharts.options as opts
from pyecharts.charts import Gauge

(
    Gauge()
    .add(series_name="业务指标", data_pair=[["完成率", 55.5]])
    .set_global_opts(
        legend_opts=opts.LegendOpts(is_show=False),
        tooltip_opts=opts.TooltipOpts(is_show=True, formatter="{a} <br/>{b} : {c}%"),
    )
    .set_series_opts(
        axisline_opts=opts.AxisLineOpts(
            linestyle_opts=opts.LineStyleOpts(
                color=[[0.3, "#67e0e3"], [0.7, "#37a2da"], [1, "#fd666d"]], width=30
            )
        )
    )
    .render("gauge_change_color.html")
)
```
