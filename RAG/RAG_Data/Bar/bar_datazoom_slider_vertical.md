---
图表类型: 柱状图 (Bar)
功能标签: [数据缩放, slider, 垂直, 交互]
数据量级标签: large, huge
适用场景: 展示大量数据，需要垂直方向查看细节。
数据适应: 适合需要垂直方向缩放查看大量数据的场景。
美观要点: 垂直slider缩放、数据清晰展示。
---

### Bar-DataZoom（slider-垂直）

这段代码展示了如何使用垂直方向的slider数据缩放方式。

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
        title_opts=opts.TitleOpts(title="Bar-DataZoom（slider-垂直）"),
        datazoom_opts=opts.DataZoomOpts(orient="vertical"),
    )
    .render("bar_datazoom_slider_vertical.html")
)
```
