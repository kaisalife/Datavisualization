---
图表类型: 折线图 (Line)
功能标签: [标注点, 最大值, 最小值, 数据对比]
数据量级标签: small, medium
适用场景: 突出展示数据的最大值和最小值，如销售数据的峰值和谷底等。
数据适应: 适合2-3个系列数据，需要突出极值点。
美观要点: 清晰的标注点、合适的颜色、明确的图例。
---

### 带标注点的折线图

这段代码展示了如何创建一个带有最大值和最小值标注点的折线图。

#### 代码
```python
import pyecharts.options as opts
from pyecharts.charts import Line
from pyecharts.faker import Faker

c = (
    Line()
    .add_xaxis(Faker.choose())
    .add_yaxis(
        "商家A",
        Faker.values(),
        markpoint_opts=opts.MarkPointOpts(data=[opts.MarkPointItem(type_="min")]),
    )
    .add_yaxis(
        "商家B",
        Faker.values(),
        markpoint_opts=opts.MarkPointOpts(data=[opts.MarkPointItem(type_="max")]),
    )
    .set_global_opts(title_opts=opts.TitleOpts(title="Line-MarkPoint"))
    .render("line_markpoint.html")
)
```
