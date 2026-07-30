---
图表类型: 桑基图 (Sankey)
功能标签: [基本桑基图, 流量可视化, 层级关系]
数据量级标签: small, medium
适用场景: 展示简单的流量分配、资金流向、物料流转等关系。
数据适应: 数据节点较少，关系相对简单的场景。
美观要点: 曲线柔和、节点标签清晰、流量透明度适中。
---

### 基础桑基图

这段代码展示了如何创建一个基础的桑基图，展示节点之间的流量关系。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Sankey

nodes = [
    {"name": "category1"},
    {"name": "category2"},
    {"name": "category3"},
    {"name": "category4"},
    {"name": "category5"},
    {"name": "category6"},
]

links = [
    {"source": "category1", "target": "category2", "value": 10},
    {"source": "category2", "target": "category3", "value": 15},
    {"source": "category3", "target": "category4", "value": 20},
    {"source": "category5", "target": "category6", "value": 25},
]
c = (
    Sankey()
    .add(
        "sankey",
        nodes,
        links,
        linestyle_opt=opts.LineStyleOpts(opacity=0.2, curve=0.5, color="source"),
        label_opts=opts.LabelOpts(position="right"),
    )
    .set_global_opts(title_opts=opts.TitleOpts(title="Sankey-基本示例"))
    .render("sankey_base.html")
)
```
