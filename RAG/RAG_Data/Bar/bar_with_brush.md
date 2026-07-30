---
图表类型: 柱状图 (Bar)
功能标签: [框选, Brush, 交互]
数据量级标签: small, medium
适用场景: 需要用户选择数据区域的场景。
数据适应: 适合需要用户进行数据区域选择和分析的场景。
美观要点: 框选功能、数据交互选择。
---

### Bar-Brush示例

这段代码展示了如何在柱状图上添加Brush框选功能，允许用户选择数据区域。

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
        title_opts=opts.TitleOpts(title="Bar-Brush示例", subtitle="我是副标题"),
        brush_opts=opts.BrushOpts(),
    )
    .render("bar_with_brush.html")
)
```
