---
图表类型: 3D散点图 (Scatter3D)
功能标签: [3D散点图, 多维度数据, 颜色映射, 大小映射]
数据量级标签: medium, large
适用场景: 展示三维空间中的数据分布关系，如食品营养成分分析、科学数据可视化等。
数据适应: 多维度数据，至少包含3个数值维度。
美观要点: 3D网格清晰、颜色渐变自然、点大小差异明显、可旋转交互。
---

### 3D散点图

这段代码展示了如何创建一个3D散点图，支持颜色映射和大小映射来展示多维度数据关系。

#### 代码
```python
import asyncio
from aiohttp import TCPConnector, ClientSession

import pyecharts.options as opts
from pyecharts.charts import Scatter3D


async def get_json_data(url: str) -> dict:
    async with ClientSession(connector=TCPConnector(ssl=False)) as session:
        async with session.get(url=url) as response:
            return await response.json()


data = asyncio.run(
    get_json_data(
        url="https://echarts.apache.org/examples/data/asset/data/nutrients.json"
    )
)

field_indices = {
    "calcium": 3,
    "calories": 12,
    "carbohydrate": 8,
    "fat": 10,
    "fiber": 5,
    "group": 1,
    "id": 16,
    "monounsat": 14,
    "name": 0,
    "polyunsat": 15,
    "potassium": 7,
    "protein": 2,
    "saturated": 13,
    "sodium": 4,
    "sugars": 9,
    "vitaminc": 6,
    "water": 11,
}

config_xAxis3D = "protein"
config_yAxis3D = "fiber"
config_zAxis3D = "sodium"
config_color = "fiber"
config_symbolSize = "vitaminc"

data = [
    [
        item[field_indices[config_xAxis3D]],
        item[field_indices[config_yAxis3D]],
        item[field_indices[config_zAxis3D]],
        item[field_indices[config_color]],
        item[field_indices[config_symbolSize]],
        index,
    ]
    for index, item in enumerate(data)
]

(
    Scatter3D()
    .add(
        series_name="",
        data=data,
        xaxis3d_opts=opts.Axis3DOpts(
            name=config_xAxis3D,
            type_="value",
        ),
        yaxis3d_opts=opts.Axis3DOpts(
            name=config_yAxis3D,
            type_="value",
        ),
        zaxis3d_opts=opts.Axis3DOpts(
            name=config_zAxis3D,
            type_="value",
        ),
        grid3d_opts=opts.Grid3DOpts(width=100, height=100, depth=100),
    )
    .set_global_opts(
        visualmap_opts=[
            opts.VisualMapOpts(
                type_="color",
                is_calculable=True,
                dimension=3,
                pos_top="10",
                max_=79 / 2,
                range_color=[
                    "#1710c0",
                    "#0b9df0",
                    "#00fea8",
                    "#00ff0d",
                    "#f5f811",
                    "#f09a09",
                    "#fe0300",
                ],
            ),
            opts.VisualMapOpts(
                type_="size",
                is_calculable=True,
                dimension=4,
                pos_bottom="10",
                max_=2.4 / 2,
                range_size=[10, 40],
            ),
        ]
    )
    .render("scatter3d.html")
)
```
