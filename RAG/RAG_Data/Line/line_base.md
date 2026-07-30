---
图表类型: 折线图 (Line)
功能标签: [趋势展示, 基础图表, 数据对比]
数据量级标签: small, medium
适用场景: 展示两组数据的趋势对比，如销售数据对比、业绩对比等。
数据适应: 适合小到中等数据量，2-3个系列数据。
美观要点: 清晰的标题、合适的颜色搭配、数据点标注。
---

### 基础折线图

这段代码展示了如何创建一个基础的折线图，用于对比两组数据的趋势。

#### 代码
```python
import pyecharts.options as opts
from pyecharts.charts import Line
from pyecharts.faker import Faker

c = (
    Line()
    .add_xaxis(Faker.choose())
    .add_yaxis("商家A", Faker.values())
    .add_yaxis("商家B", Faker.values())
    .set_global_opts(title_opts=opts.TitleOpts(title="Line-基本示例"))
    .render("line_base.html")
)
```
