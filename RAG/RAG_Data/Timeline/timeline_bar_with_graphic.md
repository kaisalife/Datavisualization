---
图表类型: 时间轴柱状图带图形组件 (Timeline-Bar-With-Graphic)
功能标签: [时间轴柱状图, 图形组件, 旋转文字, 自定义图形]
数据量级标签: small, medium
适用场景: 需要在图表上添加自定义图形或文字的多年度数据展示。
数据适应: 多年度的同类数据，每年数据结构一致。
美观要点: 自定义图形、旋转文字、视觉效果丰富、切换流畅。
---

### 时间轴柱状图带图形组件

这段代码展示了如何创建一个带图形组件的时间轴柱状图，添加了旋转的文字背景效果。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Bar, Timeline
from pyecharts.commons.utils import JsCode
from pyecharts.faker import Faker

x = Faker.choose()
tl = Timeline()
for i in range(2015, 2020):
    bar = (
        Bar()
        .add_xaxis(x)
        .add_yaxis("商家A", Faker.values())
        .add_yaxis("商家B", Faker.values())
        .set_global_opts(
            title_opts=opts.TitleOpts("某商店{}年营业额 - With Graphic 组件".format(i)),
            graphic_opts=[
                opts.GraphicGroup(
                    graphic_item=opts.GraphicItem(
                        rotation=JsCode("Math.PI / 4"),
                        bounding="raw",
                        right=100,
                        bottom=110,
                        z=100,
                    ),
                    children=[
                        opts.GraphicRect(
                            graphic_item=opts.GraphicItem(
                                left="center", top="center", z=100
                            ),
                            graphic_shape_opts=opts.GraphicShapeOpts(
                                width=400, height=50
                            ),
                            graphic_basicstyle_opts=opts.GraphicBasicStyleOpts(
                                fill="rgba(0,0,0,0.3)"
                            ),
                        ),
                        opts.GraphicText(
                            graphic_item=opts.GraphicItem(
                                left="center", top="center", z=100
                            ),
                            graphic_textstyle_opts=opts.GraphicTextStyleOpts(
                                text="某商店{}年营业额".format(i),
                                font="bold 26px Microsoft YaHei",
                                graphic_basicstyle_opts=opts.GraphicBasicStyleOpts(
                                    fill="#fff"
                                ),
                            ),
                        ),
                    ],
                )
            ],
        )
    )
    tl.add(bar, "{}年".format(i))
tl.render("timeline_bar_with_graphic.html")
```
