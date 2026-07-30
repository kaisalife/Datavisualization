---
图表类型: 折线图 (Line)
功能标签: [标注线, 平均值, 数据对比]
数据量级标签: small, medium
适用场景: 展示数据与平均值的对比，如业绩与平均值对比、销售与平均值对比等。
数据适应: 适合2-3个系列数据，需要展示平均值对比。
美观要点: 清晰的标注线、合适的颜色、明确的图例。
---

### 带标注线的折线图

这段代码展示了如何创建一个带有平均值标注线的折线图，用于对比数据与平均值。

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
        markline_opts=opts.MarkLineOpts(data=[opts.MarkLineItem(type_="average")]),
    )
    .add_yaxis(
        "商家B",
        Faker.values(),
        markline_opts=opts.MarkLineOpts(data=[opts.MarkLineItem(type_="average")]),
    )
    .set_global_opts(title_opts=opts.TitleOpts(title="Line-MarkLine"))
    .render("line_markline.html")
)
```
