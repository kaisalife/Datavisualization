---
图表类型: 漏斗图 (Funnel)
功能标签: [漏斗图, 标签位置, 内部标签]
数据量级标签: small, medium
适用场景: 需要在漏斗内部显示标签的场景。
数据适应: 适合展示数据递减的流程数据。
美观要点: 内部标签、清晰的布局。
---

### 内部标签漏斗图

这段代码展示了如何创建内部标签的漏斗图。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Funnel
from pyecharts.faker import Faker


c = (
    Funnel()
    .add(
        "商品",
        [list(z) for z in zip(Faker.choose(), Faker.values())],
        label_opts=opts.LabelOpts(position="inside"),
    )
    .set_global_opts(title_opts=opts.TitleOpts(title="Funnel-Label（inside)"))
    .render("funnel_label_inside.html")
)
```
