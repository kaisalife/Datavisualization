---
图表类型: 折线图 (Line)
功能标签: [面积图, 半透明填充, 数据对比]
数据量级标签: small, medium
适用场景: 展示两组数据的趋势对比并强调数据范围，如销售数据对比等。
数据适应: 适合2-3个系列数据，需要展示面积对比。
美观要点: 合适的填充透明度、清晰的趋势线、明确的图例。
---

### 面积折线图

这段代码展示了如何创建一个带有半透明填充的面积折线图，用于对比两组数据。

#### 代码
```python
import pyecharts.options as opts
from pyecharts.charts import Line
from pyecharts.faker import Faker

c = (
    Line()
    .add_xaxis(Faker.choose())
    .add_yaxis("商家A", Faker.values(), areastyle_opts=opts.AreaStyleOpts(opacity=0.5))
    .add_yaxis("商家B", Faker.values(), areastyle_opts=opts.AreaStyleOpts(opacity=0.5))
    .set_global_opts(title_opts=opts.TitleOpts(title="Line-面积图"))
    .render("line_area_style.html")
)
```
