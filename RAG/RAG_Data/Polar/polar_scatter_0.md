---
图表类型: 极坐标系 (Polar)
功能标签: [散点图, 基础散点, 极坐标散点
数据量级标签: medium
适用场景: 环形数据展示、极坐标散点分布、简单极坐标数据。
数据适应: 数据点数量 50-200 个，适合展示极坐标分布。
美观要点: 点大小适中、颜色协调、极坐标系清晰。
---

### 基础极坐标散点图

这段代码展示了如何创建基础的极坐标散点图，用于展示环形数据的分布。

#### 代码
```python
import random

from pyecharts import options as opts
from pyecharts.charts import Polar

data = [(i, random.randint(1, 100)) for i in range(101)]
c = (
    Polar()
    .add("", data, type_="scatter", label_opts=opts.LabelOpts(is_show=False))
    .set_global_opts(title_opts=opts.TitleOpts(title="Polar-Scatter0"))
    .render("polar_scatter_0.html")
)
```
