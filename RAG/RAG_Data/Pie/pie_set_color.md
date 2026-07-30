---
图表类型: 饼图 (Pie)
功能标签: [自定义颜色, 配色方案, 品牌配色
数据量级标签: small
适用场景: 需要自定义配色、品牌色彩、特殊配色。
数据适应: 类别数 2-10 个，自定义颜色。
美观要点: 配色协调、符合品牌风格、视觉美观。
---

### 自定义颜色饼图

这段代码展示了如何自定义饼图的颜色，实现品牌配色或特殊配色需求。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Pie
from pyecharts.faker import Faker

c = (
    Pie()
    .add("", [list(z) for z in zip(Faker.choose(), Faker.values())])
    .set_colors(["blue", "green", "yellow", "red", "pink", "orange", "purple"])
    .set_global_opts(title_opts=opts.TitleOpts(title="Pie-设置颜色"))
    .set_series_opts(label_opts=opts.LabelOpts(formatter="{b}: {c}"))
    .render("pie_set_color.html")
)
```
