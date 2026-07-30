---
图表类型: 3D柱状图 (Bar3D)
功能标签: [3D, 打卡图, 时间分布, VisualMap]
数据量级标签: medium, large
适用场景: 展示时间序列数据的三维分布，如打卡记录。
数据适应: 适合展示按小时和星期分布的时间序列数据。
美观要点: 3D打卡图效果、丰富的颜色渐变、清晰的时间轴。
---

### Bar3D-打卡图

这段代码展示了如何创建3D打卡图，展示一周7天24小时的数据分布情况。

#### 代码
```python
import pyecharts.options as opts
from pyecharts.charts import Bar3D

"""
Gallery 使用 pyecharts 2.1.0
参考地址: https://echarts.apache.org/examples/editor.html?c=bar3d-punch-card&gl=1

目前无法实现的功能:

1、光照和阴影暂时无法设置
"""

hours = [
    "12a",
    "1a",
    "2a",
    "3a",
    "4a",
    "5a",
    "6a",
    "7a",
    "8a",
    "9a",
    "10a",
    "11a",
    "12p",
    "1p",
    "2p",
    "3p",
    "4p",
    "5p",
    "6p",
    "7p",
    "8p",
    "9p",
    "10p",
    "11p",
]
days = ["Saturday", "Friday", "Thursday", "Wednesday", "Tuesday", "Monday", "Sunday"]

data = [
    [0, 0, 5],
    [0, 1, 1],
    [0, 2, 0],
    [0, 3, 0],
    [0, 4, 0],
    [0, 5, 0],
    [0, 6, 0],
    [0, 7, 0],
    [0, 8, 0],
    [0, 9, 0],
    [0, 10, 0],
    [0, 11, 2],
    [0, 12, 4],
    [0, 13, 1],
    [0, 14, 1],
    [0, 15, 3],
    [0, 16, 4],
    [0, 17, 6],
    [0, 18, 4],
    [0, 19, 4],
    [0, 20, 3],
    [0, 21, 3],
    [0, 22, 2],
    [0, 23, 5],
]
data = [[d[1], d[0], d[2]] for d in data]


(
    Bar3D()
    .add(
        series_name="",
        data=data,
        xaxis3d_opts=opts.Axis3DOpts(type_="category", data=hours),
        yaxis3d_opts=opts.Axis3DOpts(type_="category", data=days),
        zaxis3d_opts=opts.Axis3DOpts(type_="value"),
    )
    .set_global_opts(
        visualmap_opts=opts.VisualMapOpts(
            max_=20,
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
    .render("bar3d_punch_card.html")
)
```
