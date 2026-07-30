---
图表类型: 3D柱状图 (Bar3D)
功能标签: [3D, 堆叠, lambert光照]
数据量级标签: medium, large
适用场景: 展示三维空间中的堆叠数据。
数据适应: 适合需要在三维空间展示多层堆叠数据的场景。
美观要点: 3D堆叠效果、lambert光照、多层数据展示。
---

### Bar3D-堆叠柱状图示例

这段代码展示了如何创建3D堆叠柱状图，在三维空间中展示多层数据。

#### 代码
```python
import random

from pyecharts import options as opts
from pyecharts.charts import Bar3D

x_data = y_data = list(range(10))


def generate_data():
    data = []
    for j in range(10):
        for k in range(10):
            value = random.randint(0, 9)
            data.append([j, k, value * 2 + 4])
    return data


bar3d = Bar3D()
for _ in range(10):
    bar3d.add(
        "",
        generate_data(),
        shading="lambert",
        xaxis3d_opts=opts.Axis3DOpts(data=x_data, type_="value"),
        yaxis3d_opts=opts.Axis3DOpts(data=y_data, type_="value"),
        zaxis3d_opts=opts.Axis3DOpts(type_="value"),
    )
bar3d.set_global_opts(title_opts=opts.TitleOpts("Bar3D-堆叠柱状图示例"))
bar3d.set_series_opts(**{"stack": "stack"})
bar3d.render("bar3d_stack.html")
```
