---
图表类型: 柱状图 (Bar)
功能标签: [堆叠, 部分堆叠, 多系列]
数据量级标签: small, medium
适用场景: 比较多个系列的总和与各部分占比，部分系列堆叠。
数据适应: 适合需要展示部分堆叠和部分独立系列的数据。
美观要点: 部分堆叠展示、清晰的层次结构。
---

### Bar-堆叠数据（部分）

这段代码展示了如何使用部分堆叠柱状图，同时展示部分堆叠和部分独立的系列。

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
    .add_yaxis("商家C", Faker.values())
    .set_series_opts(label_opts=opts.LabelOpts(is_show=False))
    .set_global_opts(title_opts=opts.TitleOpts(title="Bar-堆叠数据（部分）"))
    .render("bar_stack1.html")
)
```
