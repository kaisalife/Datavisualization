---
图表类型: 折线图 (Line)
功能标签: [阶梯图, 阶段展示, 离散数据]
数据量级标签: small, medium
适用场景: 展示分阶段变化的数据，如价格调整、政策变化等。
数据适应: 适合单系列数据，数据点之间有明显阶段变化。
美观要点: 清晰的阶梯效果、合适的颜色、清晰的标题。
---

### 阶梯折线图

这段代码展示了如何创建一个阶梯折线图，用于展示分阶段变化的数据。

#### 代码
```python
import pyecharts.options as opts
from pyecharts.charts import Line
from pyecharts.faker import Faker

c = (
    Line()
    .add_xaxis(Faker.choose())
    .add_yaxis("商家A", Faker.values(), is_step=True)
    .set_global_opts(title_opts=opts.TitleOpts(title="Line-阶梯图"))
    .render("line_step.html")
)
```
