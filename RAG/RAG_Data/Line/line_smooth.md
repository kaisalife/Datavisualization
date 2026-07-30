---
图表类型: 折线图 (Line)
功能标签: [平滑曲线, 趋势展示, 数据对比]
数据量级标签: small, medium
适用场景: 展示平滑的趋势变化，如温度变化、销售趋势等。
数据适应: 适合2-3个系列数据，需要展示平滑趋势。
美观要点: 平滑的曲线、合适的颜色搭配、清晰的标题。
---

### 平滑折线图

这段代码展示了如何创建一个使用平滑曲线的折线图，用于展示数据的平滑趋势。

#### 代码
```python
import pyecharts.options as opts
from pyecharts.charts import Line
from pyecharts.faker import Faker

c = (
    Line()
    .add_xaxis(Faker.choose())
    .add_yaxis("商家A", Faker.values(), is_smooth=True)
    .add_yaxis("商家B", Faker.values(), is_smooth=True)
    .set_global_opts(title_opts=opts.TitleOpts(title="Line-smooth"))
    .render("line_smooth.html")
)
```
