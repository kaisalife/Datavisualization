---
图表类型: 旭日图 (Sunburst)
功能标签: [基础旭日图, 层级结构, 树形数据]
数据量级标签: small, medium
适用场景: 展示层级结构数据，如家族树、组织架构、分类目录等。
数据适应: 树形层级数据，节点有父子关系。
美观要点: 环形布局、层级清晰、标签位置合理、可交互展开。
---

### 基础旭日图

这段代码展示了如何创建一个基础的旭日图，展示家族树的层级关系。

#### 代码
```python
from pyecharts.charts import Sunburst
from pyecharts import options as opts

data = [
    opts.SunburstItem(
        name="Grandpa",
        children=[
            opts.SunburstItem(
                name="Uncle Leo",
                value=15,
                children=[
                    opts.SunburstItem(name="Cousin Jack", value=2),
                    opts.SunburstItem(
                        name="Cousin Mary",
                        value=5,
                        children=[opts.SunburstItem(name="Jackson", value=2)],
                    ),
                    opts.SunburstItem(name="Cousin Ben", value=4),
                ],
            ),
            opts.SunburstItem(
                name="Father",
                value=10,
                children=[
                    opts.SunburstItem(name="Me", value=5),
                    opts.SunburstItem(name="Brother Peter", value=1),
                ],
            ),
        ],
    ),
    opts.SunburstItem(
        name="Nancy",
        children=[
            opts.SunburstItem(
                name="Uncle Nike",
                children=[
                    opts.SunburstItem(name="Cousin Betty", value=1),
                    opts.SunburstItem(name="Cousin Jenny", value=2),
                ],
            )
        ],
    ),
]

sunburst = (
    Sunburst(init_opts=opts.InitOpts(width="1000px", height="600px"))
    .add(series_name="", data_pair=data, radius=[0, "90%"])
    .set_global_opts(title_opts=opts.TitleOpts(title="Sunburst-基本示例"))
    .set_series_opts(label_opts=opts.LabelOpts(formatter="{b}"))
    .render("basic_sunburst.html")
)
```
