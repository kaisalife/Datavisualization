---
图表类型: 柱状图 (Bar)
功能标签: [图例选中, 默认隐藏, 交互]
数据量级标签: small, medium
适用场景: 需要默认隐藏某些数据系列的场景。
数据适应: 适合多系列数据，默认只显示部分系列的场景。
美观要点: 图例交互、可选择显示系列。
---

### Bar-默认取消显示某 Series

这段代码展示了如何设置默认隐藏某个数据系列，用户可以通过图例点击显示。

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
        title_opts=opts.TitleOpts(title="Bar-默认取消显示某 Series"),
        legend_opts=opts.LegendOpts(selected_map={"商家B": False}),
    )
    .render("bar_is_selected.html")
)
```
