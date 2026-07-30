---
图表类型: 柱状图 (Bar)
功能标签: [横向, 翻转坐标轴]
数据量级标签: small, medium
适用场景: 类别名称较长时的展示。
数据适应: 适合类别标签较长，横向展示更清晰的场景。
美观要点: 横向布局、标签靠右显示。
---

### Bar-翻转 XY 轴

这段代码展示了如何创建横向柱状图，翻转XY轴，适合类别名称较长的场景。

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
    .reversal_axis()
    .set_series_opts(label_opts=opts.LabelOpts(position="right"))
    .set_global_opts(title_opts=opts.TitleOpts(title="Bar-翻转 XY 轴"))
    .render("bar_reversal_axis.html")
)
```
