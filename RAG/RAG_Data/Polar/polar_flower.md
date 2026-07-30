---
图表类型: 极坐标系 (Polar)
功能标签: [花形曲线, 数学曲线, 数据可视化艺术
数据量级标签: large
适用场景: 数据可视化艺术展示、数学曲线展示、创意数据展示。
数据适应: 数学函数生成的数据点，适合展示特殊形状。
美观要点: 曲线流畅、形状清晰、颜色协调。
---

### 极坐标花形曲线图

这段代码展示了如何使用极坐标系展示数学曲线，创建花形的数据可视化效果。

#### 代码
```python
import math

from pyecharts import options as opts
from pyecharts.charts import Polar

data = []
for i in range(361):
    t = i / 180 * math.pi
    r = math.sin(2 * t) * math.cos(2 * t)
    data.append([r, i])
c = (
    Polar()
    .add_schema(
        angleaxis_opts=opts.AngleAxisOpts(
            type_="value",
            boundary_gap=False,
            start_angle=0,
            split_number=12,
            is_clockwise=True,
        )
    )
    .add("flower", data, label_opts=opts.LabelOpts(is_show=False))
    .set_global_opts(title_opts=opts.TitleOpts(title="Polar-Flower"))
    .render("polar_flower.html")
)
```
