---
图表类型: 热力图 (Heatmap)
功能标签: [热力图, 标签显示, 密度分布, 二维数据]
数据量级标签: medium, large
适用场景: 展示二维数据的密度分布，并在单元格内显示数值标签。
数据适应: 适合二维网格数据。
美观要点: 颜色渐变、清晰的标签、视觉映射组件。
---

### 带标签显示的热力图

这段代码展示了如何创建带标签显示的热力图，在每个单元格内显示数值。

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
        "series0",
        Faker.week,
        value,
        label_opts=opts.LabelOpts(is_show=True, position="inside"),
    )
    .set_global_opts(
        title_opts=opts.TitleOpts(title="HeatMap-Label 显示"),
        visualmap_opts=opts.VisualMapOpts(),
    )
    .render("heatmap_with_label_show.html")
)
```
