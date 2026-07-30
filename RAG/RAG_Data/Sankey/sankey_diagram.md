---
图表类型: 桑基图 (Sankey)
功能标签: [能源桑基图, 异步数据获取, 大节点]
数据量级标签: medium, large
适用场景: 能源流分析、供应链分析、资金流向等复杂流量关系。
数据适应: 数据节点较多，关系复杂的场景。
美观要点: 节点边框清晰、流量曲线平滑、鼠标悬停交互。
---

### 能源桑基图

这段代码展示了如何创建一个能源流量桑基图，展示能源从生产到消费的完整流动过程。

#### 代码
```python
import asyncio
from aiohttp import TCPConnector, ClientSession

import pyecharts.options as opts
from pyecharts.charts import Sankey


async def get_json_data(url: str) -> dict:
    async with ClientSession(connector=TCPConnector(ssl=False)) as session:
        async with session.get(url=url) as response:
            return await response.json()


data = asyncio.run(
    get_json_data(url="https://echarts.apache.org/examples/data/asset/data/energy.json")
)

(
    Sankey()
    .add(
        series_name="",
        nodes=data["nodes"],
        links=data["links"],
        itemstyle_opts=opts.ItemStyleOpts(border_width=1, border_color="#aaa"),
        linestyle_opt=opts.LineStyleOpts(color="source", curve=0.5, opacity=0.5),
        tooltip_opts=opts.TooltipOpts(trigger_on="mousemove"),
    )
    .set_global_opts(title_opts=opts.TitleOpts(title="Sankey Diagram"))
    .render("sankey_diagram.html")
)
```
