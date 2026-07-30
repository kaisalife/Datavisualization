---
图表类型: 柱状图 (Bar)
功能标签: [标记点, 自定义, 坐标指定]
数据量级标签: small, medium
适用场景: 需要突出显示特定数据点的场景。
数据适应: 适合需要突出显示特定坐标位置数据点的场景。
美观要点: 自定义标记点、精确坐标定位。
---

### Bar-MarkPoint（自定义）

这段代码展示了如何在柱状图上添加自定义坐标位置的标记点。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Bar
from pyecharts.faker import Faker

x, y = Faker.choose(), Faker.values()
c = (
    Bar()
    .add_xaxis(x)
    .add_yaxis(
        "商家A",
        y,
        markpoint_opts=opts.MarkPointOpts(
            data=[opts.MarkPointItem(name="自定义标记点", coord=[x[2], y[2]], value=y[2])]
        ),
    )
    .add_yaxis("商家B", Faker.values())
    .set_global_opts(title_opts=opts.TitleOpts(title="Bar-MarkPoint（自定义）"))
    .set_series_opts(label_opts=opts.LabelOpts(is_show=False))
    .render("bar_markpoint_custom.html")
)
```
