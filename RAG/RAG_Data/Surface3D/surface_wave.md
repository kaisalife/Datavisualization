---
图表类型: 3D曲面图 (Surface3D)
功能标签: [3D曲面图, 数学函数可视化, 波动曲面, 颜色映射]
数据量级标签: medium, large
适用场景: 展示数学函数曲面、地形数据、科学数据可视化等三维曲面关系。
数据适应: 三维网格数据，x、y、z三个维度的数值数据。
美观要点: 曲面平滑、颜色渐变自然、3D网格清晰、可旋转交互。
---

### 3D波动曲面图

这段代码展示了如何创建一个3D曲面图，展示数学函数的波动曲面效果。

#### 代码
```python
import math
from typing import Union

import pyecharts.options as opts
from pyecharts.charts import Surface3D


def float_range(start: int, end: int, step: Union[int, float], round_number: int = 2):
    """
    浮点数 range
    :param start: 起始值
    :param end: 结束值
    :param step: 步长
    :param round_number: 精度
    :return: 返回一个 list
    """
    temp = []
    while True:
        if start < end:
            temp.append(round(start, round_number))
            start += step
        else:
            break
    return temp


def surface3d_data():
    for t0 in float_range(-3, 3, 0.05):
        y = t0
        for t1 in float_range(-3, 3, 0.05):
            x = t1
            z = math.sin(x**2 + y**2) * x / 3.14
            yield [x, y, z]


(
    Surface3D()
    .add(
        series_name="",
        shading="color",
        data=list(surface3d_data()),
        xaxis3d_opts=opts.Axis3DOpts(type_="value"),
        yaxis3d_opts=opts.Axis3DOpts(type_="value"),
        grid3d_opts=opts.Grid3DOpts(width=100, height=40, depth=100),
    )
    .set_global_opts(
        visualmap_opts=opts.VisualMapOpts(
            dimension=2,
            max_=1,
            min_=-1,
            range_color=[
                "#313695",
                "#4575b4",
                "#74add1",
                "#abd9e9",
                "#e0f3f8",
                "#ffffbf",
                "#fee090",
                "#fdae61",
                "#f46d43",
                "#d73027",
                "#a50026",
            ],
        )
    )
    .render("surface_wave.html")
)
```
