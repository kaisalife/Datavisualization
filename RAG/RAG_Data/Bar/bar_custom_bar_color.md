---
图表类型: 柱状图 (Bar)
功能标签: [自定义颜色, 条件颜色, JavaScript]
数据量级标签: small, medium
适用场景: 需要根据数据值动态设置颜色的场景。
数据适应: 适合需要根据数值条件展示不同颜色的数据。
美观要点: 动态颜色、条件渲染、视觉区分明显。
---

### Bar-自定义柱状颜色

这段代码展示了如何使用JavaScript函数根据数据值动态设置柱状图颜色。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Bar
from pyecharts.commons.utils import JsCode
from pyecharts.faker import Faker


color_function = """
        function (params) {
            if (params.value > 0 && params.value < 50) {
                return 'red';
            } else if (params.value > 50 && params.value < 100) {
                return 'blue';
            }
            return 'green';
        }
        """
c = (
    Bar()
    .add_xaxis(Faker.choose())
    .add_yaxis(
        "商家A",
        Faker.values(),
        itemstyle_opts=opts.ItemStyleOpts(color=JsCode(color_function)),
    )
    .add_yaxis(
        "商家B",
        Faker.values(),
        itemstyle_opts=opts.ItemStyleOpts(color=JsCode(color_function)),
    )
    .add_yaxis(
        "商家C",
        Faker.values(),
        itemstyle_opts=opts.ItemStyleOpts(color=JsCode(color_function)),
    )
    .set_global_opts(title_opts=opts.TitleOpts(title="Bar-自定义柱状颜色"))
    .render("bar_custom_bar_color.html")
)
```
