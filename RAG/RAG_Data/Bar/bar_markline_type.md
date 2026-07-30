---
图表类型: 柱状图 (Bar)
功能标签: [标记线, 最小值, 最大值, 平均值]
数据量级标签: small, medium
适用场景: 突出显示平均值、最大值等关键值。
数据适应: 适合需要突出显示统计关键值的数据展示。
美观要点: 清晰的标记线、关键值一目了然。
---

### Bar-MarkLine（指定类型）

这段代码展示了如何在柱状图上添加标记线，突出显示最小值、最大值和平均值。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Bar
from pyecharts.faker import Faker

c = (
    Bar()
    .add_xaxis(Faker.choose())
    .add_yaxis("商家A", Faker.values())
    .add_yaxis("商家B", Faker.values())
    .set_global_opts(title_opts=opts.TitleOpts(title="Bar-MarkLine（指定类型）"))
    .set_series_opts(
        label_opts=opts.LabelOpts(is_show=False),
        markline_opts=opts.MarkLineOpts(
            data=[
                opts.MarkLineItem(type_="min", name="最小值"),
                opts.MarkLineItem(type_="max", name="最大值"),
                opts.MarkLineItem(type_="average", name="平均值"),
            ]
        ),
    )
    .render("bar_markline_type.html")
)
```
