---
图表类型: 柱状图 (Bar)
功能标签: [间距调整, 多系列间距]
数据量级标签: small, medium
适用场景: 需要调整不同系列柱子间距的场景。
数据适应: 适合需要调整不同系列柱子之间间距的场景。
美观要点: 自定义系列间距、布局灵活。
---

### Bar-不同系列柱间距离

这段代码展示了如何调整不同系列柱状图之间的间距。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Bar
from pyecharts.faker import Faker


c = (
    Bar()
    .add_xaxis(Faker.choose())
    .add_yaxis("商家A", Faker.values(), gap="0%")
    .add_yaxis("商家B", Faker.values(), gap="0%")
    .set_global_opts(title_opts=opts.TitleOpts(title="Bar-不同系列柱间距离"))
    .render("bar_different_series_gap.html")
)
```
