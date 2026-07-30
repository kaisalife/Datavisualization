---
图表类型: 仪表盘 (Gauge)
功能标签: [仪表盘, 半径调整, 自定义尺寸]
数据量级标签: small
适用场景: 需要调整仪表盘大小以适应布局的场景。
数据适应: 适合展示单个百分比数据。
美观要点: 自定义半径、清晰的刻度。
---

### 自定义半径仪表盘

这段代码展示了如何创建自定义半径的仪表盘。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Gauge

c = (
    Gauge()
    .add("", [("完成率", 66.6)], radius="50%")
    .set_global_opts(title_opts=opts.TitleOpts(title="Gauge-修改 Radius 为 50%"))
    .render("gauge_change_radius.html")
)
```
