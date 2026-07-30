---
图表类型: 极坐标系 (Polar)
功能标签: [双数值轴, 极坐标折线, 数学曲线
数据量级标签: large
适用场景: 数学函数曲线展示、连续数据展示、双轴极坐标。
数据适应: 连续数据点，适合展示平滑曲线。
美观要点: 曲线流畅、双轴清晰、颜色协调。
---

### 极坐标双数值轴折线图

这段代码展示了如何使用双数值轴的极坐标系展示连续数据曲线。

#### 代码
```python
import math
import pyecharts.options as opts
from pyecharts.charts import Polar

data = []

for i in range(0, 101):
    theta = i / 100 * 360
    r = 5 * (1 + math.sin(theta / 180 * math.pi))
    data.append([r, theta])

(
    Polar()
    .add(series_name="line", data=data, label_opts=opts.LabelOpts(is_show=False))
    .add_schema(
        angleaxis_opts=opts.AngleAxisOpts(
            start_angle=0, type_="value", is_clockwise=True
        )
    )
    .set_global_opts(
        tooltip_opts=opts.TooltipOpts(trigger="axis", axis_pointer_type="cross"),
        title_opts=opts.TitleOpts(title="极坐标双数值轴"),
    )
    .render("two_value_axes_in_polar.html")
)
```
