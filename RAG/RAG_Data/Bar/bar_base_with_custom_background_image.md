---
图表类型: 柱状图 (Bar)
功能标签: [自定义背景, 背景图片, JavaScript]
数据量级标签: small, medium
适用场景: 需要自定义背景图片的场景。
数据适应: 适合需要添加自定义背景图片的展示场景。
美观要点: 自定义背景图片、丰富视觉效果。
---

### Bar-背景图基本示例

这段代码展示了如何在柱状图上添加自定义的背景图片。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Bar
from pyecharts.commons.utils import JsCode
from pyecharts.faker import Faker

c = (
    Bar(
        init_opts=opts.InitOpts(
            bg_color={"type": "pattern", "image": JsCode("img"), "repeat": "no-repeat"}
        )
    )
    .add_xaxis(Faker.choose())
    .add_yaxis("商家A", Faker.values())
    .add_yaxis("商家B", Faker.values())
    .set_global_opts(
        title_opts=opts.TitleOpts(
            title="Bar-背景图基本示例",
            subtitle="我是副标题",
            title_textstyle_opts=opts.TextStyleOpts(color="white"),
        )
    )
)
c.add_js_funcs(
    """
    var img = new Image(); img.src = 'https://s2.ax1x.com/2019/07/08/ZsS0fK.jpg';
    """
)
c.render("bar_base_with_custom_background_image.html")
```
