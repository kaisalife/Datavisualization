---
图表类型: 左右方向树形图 (Tree-Left-Right)
功能标签: [左右方向树形图, 从左到右布局, 默认方向, 折叠间隔]
数据量级标签: medium, large
适用场景: 需要从左到右展示的层级结构，如组织架构、文件目录等。
数据适应: 树形层级数据，适合横向展示。
美观要点: 从左到右布局、标签位置合理、折叠功能。
---

### 左右方向树形图

这段代码展示了如何创建一个从左到右方向的树形图，这是默认的树形图布局方向。

#### 代码
```python
import json

from pyecharts import options as opts
from pyecharts.charts import Tree


with open("flare.json", "r", encoding="utf-8") as f:
    j = json.load(f)
c = (
    Tree()
    .add("", [j], collapse_interval=2)
    .set_global_opts(title_opts=opts.TitleOpts(title="Tree-左右方向"))
    .render("tree_left_right.html")
)
```
