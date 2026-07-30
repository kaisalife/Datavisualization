---
图表类型: 树形图 (Tree)
功能标签: [基础树形图, 层级结构, 父子关系, 默认布局]
数据量级标签: small, medium
适用场景: 展示层级结构数据，如组织架构、文件目录、分类体系等。
数据适应: 树形层级数据，节点有父子关系。
美观要点: 层级清晰、节点连接自然、标签位置合理。
---

### 基础树形图

这段代码展示了如何创建一个基础的树形图，展示简单的层级关系。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Tree


data = [
    {
        "children": [
            {"name": "B"},
            {
                "children": [{"children": [{"name": "I"}], "name": "E"}, {"name": "F"}],
                "name": "C",
            },
            {
                "children": [
                    {"children": [{"name": "J"}, {"name": "K"}], "name": "G"},
                    {"name": "H"},
                ],
                "name": "D",
            },
        ],
        "name": "A",
    }
]
c = (
    Tree()
    .add("", data)
    .set_global_opts(title_opts=opts.TitleOpts(title="Tree-基本示例"))
    .render("tree_base.html")
)
```
