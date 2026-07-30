---
图表类型: ECharts配置项查询矩形树图 (Treemap-Option-Query)
功能标签: [配置项查询, 异步数据加载, 数据转换, 标签居中]
数据量级标签: large, huge
适用场景: 展示复杂的配置项层级结构，如API文档、配置体系等。
数据适应: 复杂的树形数据结构，节点数量很多。
美观要点: 标签居中、层级清晰、可交互下钻、数据转换合理。
---

### ECharts配置项查询矩形树图

这段代码展示了如何创建一个ECharts配置项查询的矩形树图，展示配置项的层级分布。

#### 代码
```python
import re
import asyncio
from aiohttp import TCPConnector, ClientSession

import pyecharts.options as opts
from pyecharts.charts import TreeMap


async def get_json_data(url: str) -> dict:
    async with ClientSession(connector=TCPConnector(ssl=False)) as session:
        async with session.get(url=url) as response:
            return await response.json()


data = asyncio.run(
    get_json_data(
        url="https://echarts.apache.org/examples/data/asset/data/"
        "ec-option-doc-statistics-201604.json"
    )
)

tree_map_data: dict = {"children": []}


def convert(source, target, base_path: str):
    for key in source:
        if base_path != "":
            path = base_path + "." + key
        else:
            path = key
        if re.match(r"/^\$/", key):
            pass
        else:
            child = {"name": path, "children": []}
            target["children"].append(child)
            if isinstance(source[key], dict):
                convert(source[key], child, path)
            else:
                target["value"] = source["$count"]


convert(source=data, target=tree_map_data, base_path="")


(
    TreeMap(init_opts=opts.InitOpts(width="1200px", height="720px"))
    .add(
        series_name="option",
        data=tree_map_data["children"],
        visual_min=300,
        leaf_depth=1,
        label_opts=opts.LabelOpts(position="inside"),
    )
    .set_global_opts(
        legend_opts=opts.LegendOpts(is_show=False),
        title_opts=opts.TitleOpts(
            title="Echarts 配置项查询分布", subtitle="2016/04", pos_left="leafDepth"
        ),
    )
    .render("echarts_option_query.html")
)
```
