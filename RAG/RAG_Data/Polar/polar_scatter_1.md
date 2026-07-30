---
图表类型: 极坐标系 (Polar)
功能标签: [多系列散点, 对比散点, 极坐标分布
数据量级标签: large
适用场景: 多组数据对比、极坐标下的分组对比。
数据适应: 多组数据，每组数据点 200-500 个。
美观要点: 不同系列颜色区分明显、点大小适中、分布清晰。
---

### 多系列极坐标散点图

这段代码展示了如何在极坐标系下创建多系列散点图，用于多组数据的对比展示。

#### 代码
```python
import random

from pyecharts import options as opts
from pyecharts.charts import Polar

c = (
    Polar()
    .add("", [(10, random.randint(1, 100)) for i in range(300)], type_="scatter")
    .add("", [(11, random.randint(1, 100)) for i in range(300)], type_="scatter")
    .set_series_opts(label_opts=opts.LabelOpts(is_show=False))
    .set_global_opts(title_opts=opts.TitleOpts(title="Polar-Scatter1"))
    .render("polar_scatter_1.html")
)
```
