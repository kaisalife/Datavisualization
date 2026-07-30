---
图表类型: 桑基图 (Sankey)
功能标签: [垂直桑基图, 自定义颜色, 节点聚焦]
数据量级标签: small, medium
适用场景: 需要垂直布局展示流量关系的场景，高度受限的展示区域。
数据适应: 数据节点适中，适合垂直展示的场景。
美观要点: 垂直排列、颜色渐变、节点聚焦效果。
---

### 垂直桑基图

这段代码展示了如何创建一个垂直布局的桑基图，支持自定义颜色和节点聚焦效果。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Sankey

colors = [
    "#67001f",
    "#b2182b",
    "#d6604d",
    "#f4a582",
    "#fddbc7",
    "#d1e5f0",
    "#92c5de",
    "#4393c3",
    "#2166ac",
    "#053061",
]
nodes = [
    {"name": "a"},
    {"name": "b"},
    {"name": "a1"},
    {"name": "b1"},
    {"name": "c"},
    {"name": "e"},
]
links = [
    {"source": "a", "target": "a1", "value": 5},
    {"source": "e", "target": "b", "value": 3},
    {"source": "a", "target": "b1", "value": 3},
    {"source": "b1", "target": "a1", "value": 1},
    {"source": "b1", "target": "c", "value": 2},
    {"source": "b", "target": "c", "value": 1},
]
c = (
    Sankey()
    .set_colors(colors)
    .add(
        "sankey",
        nodes=nodes,
        links=links,
        pos_bottom="10%",
        focus_node_mode="allEdges",
        orient="vertical",
        linestyle_opt=opts.LineStyleOpts(opacity=0.2, curve=0.5, color="source"),
        label_opts=opts.LabelOpts(position="top"),
    )
    .set_global_opts(
        title_opts=opts.TitleOpts(title="Sankey-Vertical"),
        tooltip_opts=opts.TooltipOpts(trigger="item", trigger_on="mousemove"),
    )
    .render("sankey_vertical.html")
)
```
