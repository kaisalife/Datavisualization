---
图表类型: 仪表盘 (Gauge)
功能标签: [仪表盘, 百分比展示, 业务指标]
数据量级标签: small
适用场景: 展示业务完成率、进度百分比等指标。
数据适应: 适合展示单个百分比数据。
美观要点: 清晰的刻度、指针、百分比显示。
---

### 仪表盘基本示例

这段代码展示了如何创建一个基本的仪表盘。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Gauge

c = (
    Gauge()
    .add("", [("完成率", 66.6)])
    .set_global_opts(title_opts=opts.TitleOpts(title="Gauge-基本示例"))
    .render("gauge_base.html")
)
```
