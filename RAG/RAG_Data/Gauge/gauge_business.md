---
图表类型: 仪表盘 (Gauge)
功能标签: [仪表盘, 业务指标, 提示框]
数据量级标签: small
适用场景: 展示业务完成率、进度百分比等指标，带自定义提示框。
数据适应: 适合展示单个百分比数据。
美观要点: 清晰的刻度、指针、百分比显示、自定义提示框。
---

### 业务指标仪表盘

这段代码展示了如何创建业务指标仪表盘，带自定义提示框。

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
    .render("gauge_business.html")
)
```
