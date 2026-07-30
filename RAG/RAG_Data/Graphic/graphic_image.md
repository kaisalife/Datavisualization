---
图表类型: 图形组件 (Graphic)
功能标签: [图形组件, 图片叠加, 自定义背景, 视觉增强]
数据量级标签: small, medium, large
适用场景: 在图表上叠加图片作为背景或装饰，增强视觉效果。
数据适应: 适合任何需要添加图片装饰的图表。
美观要点: 图片透明度、位置、大小。
---

### 图形组件图片示例

这段代码展示了如何使用Graphic组件在柱状图上叠加图片作为背景装饰。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Bar
from pyecharts.faker import Faker

c = (
    Bar()
    .add_xaxis(Faker.choose())
    .add_yaxis("商家A", Faker.values())
    .add_yaxis("商家B", Faker.values())
    .set_global_opts(
        title_opts=opts.TitleOpts(title="Bar-Graphic Image 组件示例"),
        graphic_opts=[
            opts.GraphicImage(
                graphic_item=opts.GraphicItem(
                    id_="logo", right=20, top=20, z=-10, bounding="raw", origin=[75, 75]
                ),
                graphic_imagestyle_opts=opts.GraphicImageStyleOpts(
                    image="https://echarts.apache.org/zh/images/favicon.png",
                    width=150,
                    height=150,
                    opacity=0.4,
                ),
            )
        ],
    )
    .render("graphic_image.html")
)
```
