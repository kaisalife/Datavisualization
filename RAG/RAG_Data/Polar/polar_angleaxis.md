---
图表类型: 极坐标系 (Polar)
功能标签: [角度轴, 堆叠柱状图, 分类数据
数据量级标签: small
适用场景: 周期性数据、周度/月度数据对比、分类堆叠展示。
数据适应: 分类数 5-10 个，适合堆叠展示。
美观要点: 堆叠清晰、颜色区分、角度轴标签明确。
---

### 角度轴极坐标堆叠柱状图

这段代码展示了如何使用角度轴创建极坐标堆叠柱状图，适合周期性数据的展示。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Polar
from pyecharts.faker import Faker

c = (
    Polar()
    .add_schema(angleaxis_opts=opts.AngleAxisOpts(data=Faker.week, type_="category"))
    .add("A", [1, 2, 3, 4, 3, 5, 1], type_="bar", stack="stack0")
    .add("B", [2, 4, 6, 1, 2, 3, 1], type_="bar", stack="stack0")
    .add("C", [1, 2, 3, 4, 1, 2, 5], type_="bar", stack="stack0")
    .set_global_opts(title_opts=opts.TitleOpts(title="Polar-AngleAxis"))
    .render("polar_angleaxis.html")
)
```
