---
图表类型: 上下方向树形图 (Tree-Top-Bottom)
功能标签: [上下方向树形图, 从上到下布局, 标签旋转, 折叠间隔]
数据量级标签: medium, large
适用场景: 需要从上到下展示的层级结构，如组织架构、决策树等。
数据适应: 树形层级数据，适合纵向展示。
美观要点: 从上到下布局、标签旋转合理、折叠功能。
---

### 上下方向树形图

这段代码展示了如何创建一个从上到下方向的树形图，标签旋转90度显示。

#### 代码
```python
import json

from pyecharts import options as opts
from pyecharts.charts import Tree


with open("flare.json", "r", encoding="utf-8") as f:
    j = json.load(f)
c = (
    Tree()
    .add(
        "",
        [j],
        collapse_interval=2,
        orient="TB",
        label_opts=opts.LabelOpts(
            position="top",
            horizontal_align="right",
            vertical_align="middle",
            rotate=-90,
        ),
    )
    .set_global_opts(title_opts=opts.TitleOpts(title="Tree-上下方向"))
    .render("tree_top_bottom.html")
)
```
