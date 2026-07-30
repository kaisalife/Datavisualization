---
图表类型: 热力图 (Heatmap)
功能标签: [热力图, 密度分布, 二维数据, 颜色渐变]
数据量级标签: medium, large
适用场景: 展示二维数据的密度分布，如时间-星期的热力图。
数据适应: 适合二维网格数据。
美观要点: 颜色渐变、清晰的坐标轴标签、视觉映射组件。
---

### 热力图基本示例

这段代码展示了如何创建一个基本的热力图，展示时间和星期的二维数据分布。

#### 代码
```python
import random

from pyecharts import options as opts
from pyecharts.charts import HeatMap
from pyecharts.faker import Faker

value = [[i, j, random.randint(0, 50)] for i in range(24) for j in range(7)]
c = (
    HeatMap()
    .add_xaxis(Faker.clock)
    .add_yaxis(
        "series0", Faker.week, value, label_opts=opts.LabelOpts(position="middle")
    )
    .set_global_opts(
        title_opts=opts.TitleOpts(title="HeatMap-基本示例"),
        visualmap_opts=opts.VisualMapOpts(),
    )
    .render("heatmap_base.html")
)
```
