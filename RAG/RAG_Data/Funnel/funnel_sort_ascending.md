---
图表类型: 漏斗图 (Funnel)
功能标签: [漏斗图, 升序排序, 内部标签]
数据量级标签: small, medium
适用场景: 需要将漏斗图从小到大升序排列的场景。
数据适应: 适合展示数据递增或递减的流程数据。
美观要点: 升序排序、内部标签、清晰的布局。
---

### 升序漏斗图

这段代码展示了如何创建升序排列的漏斗图。

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
        sort_="ascending",
        label_opts=opts.LabelOpts(position="inside"),
    )
    .set_global_opts(title_opts=opts.TitleOpts(title="Funnel-Sort（ascending）"))
    .render("funnel_sort_ascending.html")
)
```
