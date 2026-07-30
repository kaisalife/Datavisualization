---
图表类型: 柱状图 (Bar)
功能标签: [标记线, 自定义, 参考线]
数据量级标签: small, medium
适用场景: 需要添加自定义参考线的场景。
数据适应: 适合需要添加特定数值参考线的场景。
美观要点: 自定义标记线、清晰的参考标识。
---

### Bar-MarkLine（自定义）

这段代码展示了如何在柱状图上添加自定义位置的标记线作为参考线。

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
    .set_global_opts(title_opts=opts.TitleOpts(title="Bar-MarkLine（自定义）"))
    .set_series_opts(
        label_opts=opts.LabelOpts(is_show=False),
        markline_opts=opts.MarkLineOpts(
            data=[opts.MarkLineItem(y=50, name="yAxis=50")]
        ),
    )
    .render("bar_markline_custom.html")
)
```
