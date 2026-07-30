---
图表类型: 柱状图 (Bar)
功能标签: [数据缩放, inside, 交互]
数据量级标签: large, huge
适用场景: 展示大量数据，需要局部查看细节。
数据适应: 数据点较多时使用inside缩放功能提升浏览体验。
美观要点: 可交互inside缩放、数据清晰展示。
---

### Bar-DataZoom（inside）

这段代码展示了如何使用inside数据缩放方式，提升大量数据的浏览体验。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Bar
from pyecharts.faker import Faker

c = (
    Bar()
    .add_xaxis(Faker.days_attrs)
    .add_yaxis("商家A", Faker.days_values, color=Faker.rand_color())
    .set_global_opts(
        title_opts=opts.TitleOpts(title="Bar-DataZoom（inside）"),
        datazoom_opts=opts.DataZoomOpts(type_="inside"),
    )
    .render("bar_datazoom_inside.html")
)
```
