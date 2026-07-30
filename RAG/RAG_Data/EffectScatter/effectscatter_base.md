---
图表类型: 特效散点图 (EffectScatter)
功能标签: [特效散点, 动画效果, 数据展示]
数据量级标签: small, medium
适用场景: 突出显示关键数据点，增加视觉吸引力和关注度。
数据适应: 适合展示离散的、需要强调的数据点。
美观要点: 特效动画、清晰的标记。
---

### 特效散点图基本示例

这段代码展示了如何创建一个基本的特效散点图，带有动态动画效果。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import EffectScatter
from pyecharts.faker import Faker

c = (
    EffectScatter()
    .add_xaxis(Faker.choose())
    .add_yaxis("", Faker.values())
    .set_global_opts(title_opts=opts.TitleOpts(title="EffectScatter-基本示例"))
    .render("effectscatter_base.html")
)
```
