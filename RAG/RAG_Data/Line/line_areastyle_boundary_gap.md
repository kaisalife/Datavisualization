---
图表类型: 折线图 (Line)
功能标签: [面积图, 紧贴Y轴, 平滑曲线, 数据对比]
数据量级标签: small, medium
适用场景: 展示平滑的面积趋势对比，如流量数据对比、用户增长对比等。
数据适应: 适合2-3个系列数据，需要展示紧贴Y轴的面积图。
美观要点: 平滑的曲线、合适的填充透明度、紧贴Y轴的边界。
---

### 紧贴Y轴的面积折线图

这段代码展示了如何创建一个紧贴Y轴的平滑面积折线图。

#### 代码
```python
import pyecharts.options as opts
from pyecharts.charts import Line
from pyecharts.faker import Faker

c = (
    Line()
    .add_xaxis(Faker.choose())
    .add_yaxis("商家A", Faker.values(), is_smooth=True)
    .add_yaxis("商家B", Faker.values(), is_smooth=True)
    .set_series_opts(
        areastyle_opts=opts.AreaStyleOpts(opacity=0.5),
        label_opts=opts.LabelOpts(is_show=False),
    )
    .set_global_opts(
        title_opts=opts.TitleOpts(title="Line-面积图（紧贴 Y 轴）"),
        xaxis_opts=opts.AxisOpts(
            axistick_opts=opts.AxisTickOpts(is_align_with_label=True),
            is_scale=False,
            boundary_gap=False,
        ),
    )
    .render("line_areastyle_boundary_gap.html")
)
```
