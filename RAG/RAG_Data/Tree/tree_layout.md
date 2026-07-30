---
图表类型: 树形图布局 (Tree-Layout)
功能标签: [树形图布局, 径向布局, 折叠间隔, JSON数据加载]
数据量级标签: medium, large
适用场景: 展示复杂层级结构，支持节点折叠，如文件目录、知识体系等。
数据适应: 复杂的树形层级数据，节点数量较多。
美观要点: 径向布局、折叠功能、节点分布均匀。
---

### 树形图布局

这段代码展示了如何创建一个树形图，使用径向布局和折叠间隔设置。

#### 代码
```python
import json

from pyecharts import options as opts
from pyecharts.charts import Tree

with open("flare.json", "r", encoding="utf-8") as f:
    j = json.load(f)
c = (
    Tree()
    .add("", [j], collapse_interval=2, layout="radial")
    .set_global_opts(title_opts=opts.TitleOpts(title="Tree-Layout"))
    .render("tree_layout.html")
)
```
