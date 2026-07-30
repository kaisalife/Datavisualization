---
图表类型: 矩形树图层级配置 (Treemap-Levels)
功能标签: [矩形树图层级配置, 多层级样式, 边框设置, 颜色饱和度]
数据量级标签: medium, large
适用场景: 展示复杂层级结构数据，不同层级有不同样式。
数据适应: 多层级树形数据，节点数量较多。
美观要点: 不同层级不同样式、边框清晰、颜色渐变自然。
---

### 矩形树图层级配置

这段代码展示了如何创建一个带层级配置的矩形树图，不同层级有不同的样式设置。

#### 代码
```python
import json

from pyecharts import options as opts
from pyecharts.charts import TreeMap


with open("treemap.json", "r", encoding="utf-8") as f:
    data = json.load(f)
c = (
    TreeMap()
    .add(
        series_name="演示数据",
        data=data,
        levels=[
            opts.TreeMapLevelsOpts(
                treemap_itemstyle_opts=opts.TreeMapItemStyleOpts(
                    border_color="#555", border_width=4, gap_width=4
                )
            ),
            opts.TreeMapLevelsOpts(
                color_saturation=[0.3, 0.6],
                treemap_itemstyle_opts=opts.TreeMapItemStyleOpts(
                    border_color_saturation=0.7, gap_width=2, border_width=2
                ),
            ),
            opts.TreeMapLevelsOpts(
                color_saturation=[0.3, 0.5],
                treemap_itemstyle_opts=opts.TreeMapItemStyleOpts(
                    border_color_saturation=0.6, gap_width=1
                ),
            ),
            opts.TreeMapLevelsOpts(color_saturation=[0.3, 0.5]),
        ],
    )
    .set_global_opts(title_opts=opts.TitleOpts(title="TreeMap-Levels-配置"))
    .render("treemap_levels.html")
)
```
