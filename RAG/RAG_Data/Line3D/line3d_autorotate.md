---
图表类型: 3D折线图 (Line3D)
功能标签: [3D折线图, 自动旋转, 3D数据展示, 空间曲线]
数据量级标签: medium, large, huge
适用场景: 展示三维空间中的数据曲线，如数学函数曲线、空间轨迹等。
数据适应: 适合三维空间坐标数据。
美观要点: 自动旋转、3D视觉效果、颜色渐变。
---

### 3D折线图自动旋转示例

这段代码展示了如何创建一个自动旋转的3D折线图，展示弹簧曲线。

#### 代码
```python
import math

from pyecharts import options as opts
from pyecharts.charts import Line3D
from pyecharts.faker import Faker

data = []
for t in range(0, 25000):
    _t = t / 1000
    x = (1 + 0.25 * math.cos(75 * _t)) * math.cos(_t)
    y = (1 + 0.25 * math.cos(75 * _t)) * math.sin(_t)
    z = _t + 2.0 * math.sin(75 * _t)
    data.append([x, y, z])
c = (
    Line3D()
    .add(
        "",
        data,
        xaxis3d_opts=opts.Axis3DOpts(Faker.clock, type_="value"),
        yaxis3d_opts=opts.Axis3DOpts(Faker.week_en, type_="value"),
        grid3d_opts=opts.Grid3DOpts(
            width=100, depth=100, rotate_speed=150, is_rotate=True
        ),
    )
    .set_global_opts(
        visualmap_opts=opts.VisualMapOpts(
            max_=30, min_=0, range_color=Faker.visual_color
        ),
        title_opts=opts.TitleOpts(title="Line3D-旋转的弹簧"),
    )
    .render("line3d_autorotate.html")
)
```
