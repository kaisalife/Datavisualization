---
图表类型: 右左方向树形图 (Tree-Right-Left)
功能标签: [右左方向树形图, 从右到左布局, 反向方向, 折叠间隔]
数据量级标签: medium, large
适用场景: 需要从右到左展示的层级结构，如流程溯源、数据流向等。
数据适应: 树形层级数据，适合反向横向展示。
美观要点: 从右到左布局、标签位置合理、折叠功能。
---

### 右左方向树形图

这段代码展示了如何创建一个从右到左方向的树形图，反向横向展示层级关系。

#### 代码
```python
import json

from pyecharts import options as opts
from pyecharts.charts import Tree

with open("flare.json", "r", encoding="utf-8") as f:
    j = json.load(f)
c = (
    Tree()
    .add("", [j], collapse_interval=2, orient="RL")
    .set_global_opts(title_opts=opts.TitleOpts(title="Tree-右左方向"))
    .render("tree_right_left.html")
)
```
