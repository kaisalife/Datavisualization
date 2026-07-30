---
图表类型: 柱状图 (Bar)
功能标签: [坐标轴名称, XY轴配置]
数据量级标签: small, medium
适用场景: 需要明确坐标轴含义的场景。
数据适应: 适合需要给坐标轴添加说明名称的所有场景。
美观要点: 清晰的坐标轴名称、数据含义明确。
---

### Bar-XY 轴名称

这段代码展示了如何设置X轴和Y轴的名称，让图表含义更清晰。

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
        title_opts=opts.TitleOpts(title="Bar-XY 轴名称"),
        yaxis_opts=opts.AxisOpts(name="我是 Y 轴"),
        xaxis_opts=opts.AxisOpts(name="我是 X 轴"),
    )
    .render("bar_xyaxis_name.html")
)
```
