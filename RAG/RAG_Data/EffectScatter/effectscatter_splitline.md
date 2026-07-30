---
图表类型: 特效散点图 (EffectScatter)
功能标签: [特效散点, 分割线, 网格辅助]
数据量级标签: small, medium
适用场景: 需要参考网格线来定位数据点的场景。
数据适应: 适合展示离散的、需要强调的数据点。
美观要点: 特效动画、清晰的分割线网格。
---

### 带分割线的特效散点图

这段代码展示了如何创建带分割线的特效散点图，便于定位和阅读数据。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import EffectScatter
from pyecharts.faker import Faker

c = (
    EffectScatter()
    .add_xaxis(Faker.choose())
    .add_yaxis("", Faker.values())
    .set_global_opts(
        title_opts=opts.TitleOpts(title="EffectScatter-显示分割线"),
        xaxis_opts=opts.AxisOpts(splitline_opts=opts.SplitLineOpts(is_show=True)),
        yaxis_opts=opts.AxisOpts(splitline_opts=opts.SplitLineOpts(is_show=True)),
    )
    .render("effectscatter_splitline.html")
)
```
