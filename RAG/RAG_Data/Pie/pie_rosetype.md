---
图表类型: 饼图 (Pie)
功能标签: [玫瑰图, 面积玫瑰图, 半径玫瑰图, 对比展示
数据量级标签: small
适用场景: 需要视觉效果突出、数据对比展示、需要特殊效果。
数据适应: 类别数 3-10 个，两种玫瑰图效果。
美观要点: 玫瑰图效果明显、左右对比清晰、视觉冲击力强。
---

### 玫瑰图对比展示

这段代码展示了如何创建玫瑰图，包括半径玫瑰图和面积玫瑰图，用于数据对比展示。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Pie
from pyecharts.faker import Faker


v = Faker.choose()
c = (
    Pie()
    .add(
        "",
        [list(z) for z in zip(v, Faker.values())],
        radius=["30%", "75%"],
        center=["25%", "50%"],
        rosetype="radius",
        label_opts=opts.LabelOpts(is_show=False),
    )
    .add(
        "",
        [list(z) for z in zip(v, Faker.values())],
        radius=["30%", "75%"],
        center=["75%", "50%"],
        rosetype="area",
    )
    .set_global_opts(title_opts=opts.TitleOpts(title="Pie-玫瑰图示例"))
    .render("pie_rosetype.html")
)
```
