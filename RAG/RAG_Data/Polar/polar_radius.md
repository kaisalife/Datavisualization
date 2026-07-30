---
图表类型: 极坐标系 (Polar)
功能标签: [半径轴, 极坐标柱状图, 分类数据
数据量级标签: small
适用场景: 分类数据对比、环形数据展示、径向数据展示。
数据适应: 分类数 5-10 个，适合径向柱状图展示。
美观要点: 径向清晰、颜色区分、标签明确。
---

### 半径轴极坐标柱状图

这段代码展示了如何使用半径轴创建极坐标柱状图，用于分类数据的径向展示。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Polar
from pyecharts.faker import Faker

c = (
    Polar()
    .add_schema(
        radiusaxis_opts=opts.RadiusAxisOpts(data=Faker.week, type_="category"),
        angleaxis_opts=opts.AngleAxisOpts(is_clockwise=True, max_=10),
    )
    .add("A", [1, 2, 3, 4, 3, 5, 1], type_="bar")
    .set_global_opts(title_opts=opts.TitleOpts(title="Polar-RadiusAxis"))
    .set_series_opts(label_opts=opts.LabelOpts(is_show=True))
    .render("polar_radius.html")
)
```
