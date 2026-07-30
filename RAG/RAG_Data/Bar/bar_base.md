---
图表类型: 柱状图 (Bar)
功能标签: [基础, 多系列]
数据量级标签: small, medium
适用场景: 基础数据对比展示，多系列数据比较。
数据适应: 适合中小数据量的基础对比。
美观要点: 简洁清晰、默认样式。
---

### Bar-基本示例

这段代码展示了如何使用pyecharts创建基础的柱状图，用于多系列数据对比。

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
    .set_global_opts(title_opts=opts.TitleOpts(title="Bar-基本示例", subtitle="我是副标题"))
    .render("bar_base.html")
)
```
