---
图表类型: 水球图 (Liquid)
功能标签: [水球图, 百分比展示, 进度展示, 动态效果]
数据量级标签: small
适用场景: 展示百分比进度，如任务完成率、目标达成率等。
数据适应: 适合展示单个或多个百分比数据。
美观要点: 水球动画、清晰的百分比显示、合适的颜色。
---

### 水球图基本示例

这段代码展示了如何创建一个基本的水球图，展示百分比进度。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Liquid

c = (
    Liquid()
    .add("lq", [0.6, 0.7])
    .set_global_opts(title_opts=opts.TitleOpts(title="Liquid-基本示例"))
    .render("liquid_base.html")
)
```
