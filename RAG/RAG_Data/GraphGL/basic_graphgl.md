---
图表类型: 3D力导向图 (GraphGL)
功能标签: [3D力导向图, 网络拓扑, 力导向布局, WebGL渲染]
数据量级标签: large, huge
适用场景: 展示大规模网络拓扑关系，如社交网络、知识图谱等。
数据适应: 适合包含大量节点和边的网络数据。
美观要点: 深色模式、清晰的节点和连线、力导向布局。
---

### 3D力导向图基本示例

这段代码展示了如何创建一个基于WebGL的3D力导向图，用于展示大规模网络数据。

#### 代码
```python
import random

from pyecharts import options as opts
from pyecharts.charts import GraphGL


nodes = []
for i in range(50):
    for j in range(50):
        nodes.append(
            opts.GraphGLNode(
                x=random.random() * 958,
                y=random.random() * 777,
                value=1,
            )
        )

links = []
for i in range(50):
    for j in range(50):
        if i < 50 - 1:
            links.append(
                opts.GraphGLLink(
                    source=i + j * 50,
                    target=i + 1 + j * 50,
                    value=1,
                )
            )
        if j < 50 - 1:
            links.append(
                opts.GraphGLLink(
                    source=i + j * 50,
                    target=i + (j + 1) * 50,
                    value=1,
                )
            )

c = (
    GraphGL(init_opts=opts.InitOpts())
    .add(
        series_name="",
        nodes=nodes,
        links=links,
        itemstyle_opts=opts.ItemStyleOpts(color="rgba(255,255,255,0.8)"),
        linestyle_opts=opts.LineStyleOpts(color="rgba(255,255,255,0.8)", width=3),
        force_atlas2_opts=opts.GraphGLForceAtlas2Opts(
            steps=5,
            edge_weight_influence=4,
        ),
    )
    .set_dark_mode()
    .render("basic_graphgl.html")
)
```
