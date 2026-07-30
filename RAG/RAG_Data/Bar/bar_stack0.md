---
图表类型: 柱状图 (Bar)
功能标签: [堆叠, 多系列]
数据量级标签: small, medium
适用场景: 比较多个系列的总和与各部分占比。
数据适应: 适合需要展示总量和各部分组成的数据。
美观要点: 堆叠展示、清晰的层次结构。
---

### Bar-堆叠数据（全部）

这段代码展示了如何使用堆叠柱状图，同时展示多个系列的总和与各部分占比。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Bar
from pyecharts.faker import Faker

c = (
    Bar()
    .add_xaxis(Faker.choose())
    .add_yaxis("商家A", Faker.values(), stack="stack1")
    .add_yaxis("商家B", Faker.values(), stack="stack1")
    .set_series_opts(label_opts=opts.LabelOpts(is_show=False))
    .set_global_opts(title_opts=opts.TitleOpts(title="Bar-堆叠数据（全部）"))
    .render("bar_stack0.html")
)
```
