---
图表类型: 柱状图 (Bar)
功能标签: [圆角, 渐变, 自定义样式]
数据量级标签: small, medium
适用场景: 需要美观展示的场景。
数据适应: 适合需要视觉美化的数据展示。
美观要点: 圆角边框、渐变颜色、阴影效果。
---

### Bar-渐变圆柱

这段代码展示了如何创建带圆角和渐变颜色的柱状图，提升视觉效果。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Bar
from pyecharts.commons.utils import JsCode
from pyecharts.faker import Faker

c = (
    Bar()
    .add_xaxis(Faker.choose())
    .add_yaxis("商家A", Faker.values(), category_gap="60%")
    .set_series_opts(
        itemstyle_opts={
            "normal": {
                "color": JsCode(
                    """new echarts.graphic.LinearGradient(0, 0, 0, 1, [{
                offset: 0,
                color: 'rgba(0, 244, 255, 1)'
            }, {
                offset: 1,
                color: 'rgba(0, 77, 167, 1)'
            }], false)"""
                ),
                "barBorderRadius": [30, 30, 30, 30],
                "shadowColor": "rgb(0, 160, 221)",
            }
        }
    )
    .set_global_opts(title_opts=opts.TitleOpts(title="Bar-渐变圆柱"))
    .render("bar_border_radius.html")
)
```
