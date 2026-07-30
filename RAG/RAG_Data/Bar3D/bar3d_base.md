---
图表类型: 3D柱状图 (Bar3D)
功能标签: [3D, 基础, VisualMap]
数据量级标签: medium, large
适用场景: 展示三维数据关系。
数据适应: 适合需要在三维空间展示数据分布的场景。
美观要点: 3D视觉效果、颜色映射、可旋转视角。
---

### Bar3D-基本示例

这段代码展示了如何创建基本的3D柱状图，展示三维空间中的数据分布。

#### 代码
```python
import random

from pyecharts import options as opts
from pyecharts.charts import Bar3D
from pyecharts.faker import Faker


data = [(i, j, random.randint(0, 12)) for i in range(6) for j in range(24)]
c = (
    Bar3D()
    .add(
        "",
        [[d[1], d[0], d[2]] for d in data],
        xaxis3d_opts=opts.Axis3DOpts(Faker.clock, type_="category"),
        yaxis3d_opts=opts.Axis3DOpts(Faker.week_en, type_="category"),
        zaxis3d_opts=opts.Axis3DOpts(type_="value"),
    )
    .set_global_opts(
        visualmap_opts=opts.VisualMapOpts(max_=20),
        title_opts=opts.TitleOpts(title="Bar3D-基本示例"),
    )
    .render("bar3d_base.html")
)
```
