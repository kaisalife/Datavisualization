---
图表类型: 柱状图 (Bar)
功能标签: [直方图, 无间距]
数据量级标签: small, medium
适用场景: 数据分布分析。
数据适应: 适合展示数据分布情况，柱子之间无间距。
美观要点: 紧密排列、直方图风格。
---

### Bar-直方图

这段代码展示了如何创建直方图样式的柱状图，柱子之间无间距。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Bar
from pyecharts.faker import Faker

c = (
    Bar()
    .add_xaxis(Faker.choose())
    .add_yaxis("商家A", Faker.values(), category_gap=0, color=Faker.rand_color())
    .set_global_opts(title_opts=opts.TitleOpts(title="Bar-直方图"))
    .render("bar_histogram.html")
)
```
