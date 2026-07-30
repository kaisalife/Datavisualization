---
图表类型: 图片组件 (Image)
功能标签: [图片组件, 图片展示, 自定义样式]
数据量级标签: small
适用场景: 直接展示图片，作为独立组件使用。
数据适应: 适合展示静态图片。
美观要点: 合适的尺寸、位置、样式。
---

### 图片组件基本示例

这段代码展示了如何使用Image组件直接展示图片。

#### 代码
```python
from pyecharts.components import Image
from pyecharts.options import ComponentTitleOpts


image = Image()

img_src = (
    "https://user-images.githubusercontent.com/19553554/"
    "71825144-2d568180-30d6-11ea-8ee0-63c849cfd934.png"
)
image.add(
    src=img_src,
    style_opts={"width": "200px", "height": "200px", "style": "margin-top: 20px"},
)
image.set_global_opts(
    title_opts=ComponentTitleOpts(title="Image-基本示例", subtitle="我是副标题支持换行哦")
)
image.render("image_base.html")
```
