---
图表类型: 极坐标系 (Polar)
功能标签: [特效散点, 动态效果, 视觉突出
数据量级标签: small
适用场景: 需要突出显示的数据、重点数据标记、视觉效果展示。
数据适应: 数据点数量 5-20 个，特效散点突出显示。
美观要点: 特效明显、点大小适中、颜色醒目。
---

### 极坐标特效散点图

这段代码展示了如何在极坐标系下创建特效散点图，用于突出显示重要数据点。

#### 代码
```python
import random

from pyecharts import options as opts
from pyecharts.charts import Polar


data = [(i, random.randint(1, 100)) for i in range(10)]
c = (
    Polar()
    .add(
        "",
        data,
        type_="effectScatter",
        effect_opts=opts.EffectOpts(scale=10, period=5),
        label_opts=opts.LabelOpts(is_show=False),
    )
    .set_global_opts(title_opts=opts.TitleOpts(title="Polar-EffectScatter"))
    .render("polar_effectscatter.html")
)
```
