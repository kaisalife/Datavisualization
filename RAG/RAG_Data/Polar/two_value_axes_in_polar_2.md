---
图表类型: 极坐标系 (Polar)
功能标签: [双数值轴, 花形曲线, 数学曲线
数据量级标签: large
适用场景: 复杂数学曲线展示、花形数据展示、双轴极坐标。
数据适应: 连续数据点，适合展示复杂形状曲线。
美观要点: 曲线流畅、双轴清晰、形状明确。
---

### 极坐标双数值轴花形曲线图

这段代码展示了如何使用双数值轴的极坐标系展示复杂的花形数学曲线。

#### 代码
```python
import math
import pyecharts.options as opts
from pyecharts.charts import Polar

data = []

for i in range(0, 360 + 1):
    t = i / 180 * math.pi
    r = math.sin(2 * t) * math.cos(2 * t)
    data.append([r, i])

(
    Polar()
    .add(
        series_name="line",
        data=data,
        label_opts=opts.LabelOpts(is_show=False),
        symbol_size=0,
    )
    .add_schema(
        angleaxis_opts=opts.AngleAxisOpts(
            start_angle=0, type_="value", is_clockwise=True
        ),
        radiusaxis_opts=opts.RadiusAxisOpts(min_=0),
    )
    .set_global_opts(
        tooltip_opts=opts.TooltipOpts(trigger="axis", axis_pointer_type="cross"),
        title_opts=opts.TitleOpts(title="极坐标双数值轴"),
    )
    .render("two_value_axes_in_polar_2.html")
)
```
