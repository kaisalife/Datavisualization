---
图表类型: 特效散点图 (EffectScatter)
功能标签: [特效散点, 自定义符号, 视觉多样性]
数据量级标签: small, medium
适用场景: 需要通过不同符号区分不同类型数据的场景。
数据适应: 适合展示离散的、需要强调的数据点。
美观要点: 特效动画、自定义的标记符号。
---

### 带自定义符号的特效散点图

这段代码展示了如何使用不同的符号（Symbol）来标记数据点，增加视觉多样性。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import EffectScatter
from pyecharts.faker import Faker
from pyecharts.globals import SymbolType

c = (
    EffectScatter()
    .add_xaxis(Faker.choose())
    .add_yaxis("", Faker.values(), symbol=SymbolType.ARROW)
    .set_global_opts(title_opts=opts.TitleOpts(title="EffectScatter-不同Symbol"))
    .render("effectscatter_symbol.html")
)
```
