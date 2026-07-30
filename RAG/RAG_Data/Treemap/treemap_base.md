---
图表类型: 矩形树图 (Treemap)
功能标签: [基础矩形树图, 层级结构, 面积映射, 数据可视化]
数据量级标签: small, medium
适用场景: 展示层级结构数据的占比关系，如文件大小占比、预算分配等。
数据适应: 树形层级数据，每个节点有数值。
美观要点: 矩形大小与数值成正比、层级清晰、标签位置合理。
---

### 基础矩形树图

这段代码展示了如何创建一个基础的矩形树图，展示层级结构数据的占比关系。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import TreeMap

data = [
    {"value": 40, "name": "我是A"},
    {
        "value": 180,
        "name": "我是B",
        "children": [
            {
                "value": 76,
                "name": "我是B.children",
                "children": [
                    {"value": 12, "name": "我是B.children.a"},
                    {"value": 28, "name": "我是B.children.b"},
                    {"value": 20, "name": "我是B.children.c"},
                    {"value": 16, "name": "我是B.children.d"},
                ],
            }
        ],
    },
]

c = (
    TreeMap()
    .add("演示数据", data)
    .set_global_opts(title_opts=opts.TitleOpts(title="TreeMap-基本示例"))
    .render("treemap_base.html")
)
```
