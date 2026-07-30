---
图表类型: 柱状图 (Bar)
功能标签: [Y轴格式化, 标签格式化]
数据量级标签: small, medium
适用场景: 需要自定义坐标轴标签格式的场景。
数据适应: 适合需要给Y轴标签添加单位或自定义格式的场景。
美观要点: 自定义标签格式、数据含义明确。
---

### Bar-Y 轴 formatter

这段代码展示了如何自定义Y轴标签的格式化，添加单位或自定义显示格式。

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
    .set_global_opts(
        title_opts=opts.TitleOpts(title="Bar-Y 轴 formatter"),
        yaxis_opts=opts.AxisOpts(axislabel_opts=opts.LabelOpts(formatter="{value} /月")),
    )
    .render("bar_yaxis_formatter.html")
)
```
