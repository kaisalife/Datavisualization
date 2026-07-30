---
图表类型: 漏斗图 (Funnel)
功能标签: [漏斗图, 流程转化, 数据递减]
数据量级标签: small, medium
适用场景: 展示业务流程转化漏斗，如销售漏斗、用户转化路径等。
数据适应: 适合展示数据递减的流程数据。
美观要点: 清晰的标签、漏斗形状。
---

### 漏斗图基本示例

这段代码展示了如何创建一个基本的漏斗图。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Funnel
from pyecharts.faker import Faker

c = (
    Funnel()
    .add("商品", [list(z) for z in zip(Faker.choose(), Faker.values())])
    .set_global_opts(title_opts=opts.TitleOpts(title="Funnel-基本示例"))
    .render("funnel_base.html")
)
```
