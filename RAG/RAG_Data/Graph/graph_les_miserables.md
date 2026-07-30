---
图表类型: 关系图 (Graph)
功能标签: [关系图, 网络拓扑, 环形布局, 分类节点]
数据量级标签: medium, large
适用场景: 展示复杂的关系网络，如小说人物关系、社交网络等。
数据适应: 适合包含节点和边的网络数据，支持节点分类。
美观要点: 环形布局、分类颜色、曲线连线。
---

### 悲惨世界人物关系图

这段代码展示了如何创建一个环形布局的关系图，展示小说《悲惨世界》中的人物关系。

#### 代码
```python
import json

from pyecharts import options as opts
from pyecharts.charts import Graph


with open("les-miserables.json", "r", encoding="utf-8") as f:
    j = json.load(f)
    nodes = j["nodes"]
    links = j["links"]
    categories = j["categories"]

c = (
    Graph(init_opts=opts.InitOpts(width="1000px", height="600px"))
    .add(
        "",
        nodes=nodes,
        links=links,
        categories=categories,
        layout="circular",
        is_rotate_label=True,
        linestyle_opts=opts.LineStyleOpts(color="source", curve=0.3),
        label_opts=opts.LabelOpts(position="right"),
    )
    .set_global_opts(
        title_opts=opts.TitleOpts(title="Graph-Les Miserables"),
        legend_opts=opts.LegendOpts(orient="vertical", pos_left="2%", pos_top="20%"),
    )
    .render("graph_les_miserables.html")
)
```
