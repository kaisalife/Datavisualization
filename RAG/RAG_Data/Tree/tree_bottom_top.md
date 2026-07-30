---
图表类型: 下上方向树形图 (Tree-Bottom-Top)
功能标签: [下上方向树形图, 从下到上布局, 标签旋转, 折叠间隔]
数据量级标签: medium, large
适用场景: 需要从下到上展示的层级结构，如流程溯源、数据流向等。
数据适应: 树形层级数据，适合从下向上展示。
美观要点: 从下到上布局、标签旋转合理、折叠功能。
---

### 下上方向树形图

这段代码展示了如何创建一个从下到上方向的树形图，标签旋转90度显示。

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
        orient="BT",
        label_opts=opts.LabelOpts(
            position="top",
            horizontal_align="right",
            vertical_align="middle",
            rotate=-90,
        ),
    )
    .set_global_opts(title_opts=opts.TitleOpts(title="Tree-下上方向"))
    .render("tree_bottom_top.html")
)
```
