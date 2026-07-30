---
图表类型: 桑基图 (Sankey)
功能标签: [层级设置桑基图, JSON数据加载, 不同层级颜色]
数据量级标签: medium, large
适用场景: 需要按层级区分显示的复杂流量关系，如产品生产流程、组织架构等。
数据适应: 数据有明确层级关系的场景。
美观要点: 不同层级不同颜色、层级清晰、颜色对比鲜明。
---

### 带层级设置的桑基图

这段代码展示了如何创建一个带层级设置的桑基图，通过不同颜色区分不同层级的节点。

#### 代码
```python
import json

from pyecharts import options as opts
from pyecharts.charts import Sankey

with open("product.json", "r", encoding="utf-8") as f:
    j = json.load(f)
c = (
    Sankey()
    .add(
        "sankey",
        nodes=j["nodes"],
        links=j["links"],
        pos_top="10%",
        levels=[
            opts.SankeyLevelsOpts(
                depth=0,
                itemstyle_opts=opts.ItemStyleOpts(color="#fbb4ae"),
                linestyle_opts=opts.LineStyleOpts(color="source", opacity=0.6),
            ),
            opts.SankeyLevelsOpts(
                depth=1,
                itemstyle_opts=opts.ItemStyleOpts(color="#b3cde3"),
                linestyle_opts=opts.LineStyleOpts(color="source", opacity=0.6),
            ),
            opts.SankeyLevelsOpts(
                depth=2,
                itemstyle_opts=opts.ItemStyleOpts(color="#ccebc5"),
                linestyle_opts=opts.LineStyleOpts(color="source", opacity=0.6),
            ),
            opts.SankeyLevelsOpts(
                depth=3,
                itemstyle_opts=opts.ItemStyleOpts(color="#decbe4"),
                linestyle_opts=opts.LineStyleOpts(color="source", opacity=0.6),
            ),
        ],
        linestyle_opt=opts.LineStyleOpts(curve=0.5),
    )
    .set_global_opts(
        title_opts=opts.TitleOpts(title="Sankey-Level Settings"),
        tooltip_opts=opts.TooltipOpts(trigger="item", trigger_on="mousemove"),
    )
    .render("sankey_with_level_setting.html")
)
```
