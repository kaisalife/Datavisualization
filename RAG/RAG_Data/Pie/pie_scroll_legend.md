---
图表类型: 饼图 (Pie)
功能标签: [滚动图例, 大量类别, 大数据量
数据量级标签: medium
适用场景: 类别数较多、需要滚动查看图例。
数据适应: 类别数 10-30 个，图例可滚动。
美观要点: 图例布局合理、滚动流畅、不影响饼图清晰。
---

### 滚动图例饼图

这段代码展示了如何创建带滚动图例的饼图，适合类别数较多的场景。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Pie
from pyecharts.faker import Faker

c = (
    Pie()
    .add(
        "",
        [
            list(z)
            for z in zip(
                Faker.choose() + Faker.choose() + Faker.choose(),
                Faker.values() + Faker.values() + Faker.values(),
            )
        ],
        center=["40%", "50%"],
    )
    .set_global_opts(
        title_opts=opts.TitleOpts(title="Pie-Legend 滚动"),
        legend_opts=opts.LegendOpts(type_="scroll", pos_left="80%", orient="vertical"),
    )
    .set_series_opts(label_opts=opts.LabelOpts(formatter="{b}: {c}"))
    .render("pie_scroll_legend.html")
)
```
