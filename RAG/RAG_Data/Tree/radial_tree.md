---
图表类型: 径向树形图 (Tree-Radial)
功能标签: [径向树形图, 环形布局, 异步数据加载, 空圆圈符号]
数据量级标签: medium, large
适用场景: 展示复杂层级结构，如文件系统、知识图谱等。
数据适应: 复杂的树形层级数据，节点数量较多。
美观要点: 环形布局美观、节点分布均匀、符号样式统一。
---

### 径向树形图

这段代码展示了如何创建一个径向树形图，使用环形布局展示复杂层级关系。

#### 代码
```python
import asyncio
from aiohttp import TCPConnector, ClientSession

import pyecharts.options as opts
from pyecharts.charts import Tree


async def get_json_data(url: str) -> dict:
    async with ClientSession(connector=TCPConnector(ssl=False)) as session:
        async with session.get(url=url) as response:
            return await response.json()


data = asyncio.run(
    get_json_data(url="https://echarts.apache.org/examples/data/asset/data/flare.json")
)

(
    Tree()
    .add(
        series_name="",
        data=[data],
        pos_top="18%",
        pos_bottom="14%",
        layout="radial",
        symbol="emptyCircle",
        symbol_size=7,
    )
    .set_global_opts(
        tooltip_opts=opts.TooltipOpts(trigger="item", trigger_on="mousemove")
    )
    .render("radial_tree.html")
)
```
