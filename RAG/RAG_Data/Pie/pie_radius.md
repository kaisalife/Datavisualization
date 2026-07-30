---
图表类型: 饼图 (Pie)
功能标签: [半径调整, 环形图, 垂直图例
数据量级标签: small
适用场景: 需要调整饼图大小、环形图展示、垂直图例布局。
数据适应: 类别数 2-10 个，可以自定义内外半径。
美观要点: 环形宽度合适、图例位置合理、整体协调。
---

### 调整半径环形图

这段代码展示了如何调整饼图的半径，创建环形图并设置垂直图例。

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
        radius=["40%", "75%"],
    )
    .set_global_opts(
        title_opts=opts.TitleOpts(title="Pie-Radius"),
        legend_opts=opts.LegendOpts(orient="vertical", pos_top="15%", pos_left="2%"),
    )
    .set_series_opts(label_opts=opts.LabelOpts(formatter="{b}: {c}"))
    .render("pie_radius.html")
)
```
