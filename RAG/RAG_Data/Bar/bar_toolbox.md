---
图表类型: 柱状图 (Bar)
功能标签: [工具箱, 交互, 数据导出]
数据量级标签: small, medium
适用场景: 需要用户交互操作的场景。
数据适应: 适合需要用户进行数据探索、导出等操作的场景。
美观要点: 完整工具箱、丰富交互功能。
---

### Bar-显示 ToolBox

这段代码展示了如何在柱状图上显示工具箱，提供数据导出、刷新等交互功能。

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
        title_opts=opts.TitleOpts(title="Bar-显示 ToolBox"),
        toolbox_opts=opts.ToolboxOpts(),
        legend_opts=opts.LegendOpts(is_show=False),
    )
    .render("bar_toolbox.html")
)
```
