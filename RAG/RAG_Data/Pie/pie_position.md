---
图表类型: 饼图 (Pie)
功能标签:  [位置调整, 图例位置, 自定义布局
数据量级标签: small
适用场景: 需要自定义图表布局、需要调整饼图位置的场景。
数据适应: 类别数 2-10 个，需要配合布局调整。
美观要点: 位置合理、图例搭配和谐、整体布局美观。
---

### 调整位置自定义布局饼图

这段代码展示了如何调整饼图和图例的位置，实现自定义的图表布局。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Pie
from pyecharts.faker import Faker

c = (
    Pie()
    .add(
        "",
        [list(z) for z in zip(Faker.choose(), Faker.values())],
        center=["35%", "50%"],
    )
    .set_global_opts(
        title_opts=opts.TitleOpts(title="Pie-调整位置"),
        legend_opts=opts.LegendOpts(pos_left="15%"),
    )
    .set_series_opts(label_opts=opts.LabelOpts(formatter="{b}: {c}"))
    .render("pie_position.html")
)
```
