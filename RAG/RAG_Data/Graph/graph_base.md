---
图表类型: 关系图 (Graph)
功能标签: [关系图, 网络拓扑, 力导向布局]
数据量级标签: small, medium
适用场景: 展示节点之间的关系网络，如社交网络、知识图谱等。
数据适应: 适合包含节点和边的网络数据。
美观要点: 清晰的节点和连线、力导向布局。
---

### 关系图基本示例

这段代码展示了如何创建一个基本的关系图，展示节点之间的关系。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Graph

nodes = [
    {"name": "结点1", "symbolSize": 10},
    {"name": "结点2", "symbolSize": 20},
    {"name": "结点3", "symbolSize": 30},
    {"name": "结点4", "symbolSize": 40},
    {"name": "结点5", "symbolSize": 50},
    {"name": "结点6", "symbolSize": 40},
    {"name": "结点7", "symbolSize": 30},
    {"name": "结点8", "symbolSize": 20},
]
links = []
for i in nodes:
    for j in nodes:
        links.append({"source": i.get("name"), "target": j.get("name")})
c = (
    Graph()
    .add("", nodes, links, repulsion=8000)
    .set_global_opts(title_opts=opts.TitleOpts(title="Graph-基本示例"))
    .render("graph_base.html")
)
```
