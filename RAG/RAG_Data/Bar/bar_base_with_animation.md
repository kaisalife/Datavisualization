---
图表类型: 柱状图 (Bar)
功能标签: [动画, 动画延迟, 动画效果]
数据量级标签: small, medium
适用场景: 需要视觉增强的展示场景。
数据适应: 适合需要动画效果提升用户体验的场景。
美观要点: 流畅动画、弹性效果。
---

### Bar-动画配置基本示例

这段代码展示了如何配置柱状图的动画效果，包括延迟和动画缓动函数。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Bar
from pyecharts.faker import Faker


c = (
    Bar(
        init_opts=opts.InitOpts(
            animation_opts=opts.AnimationOpts(
                animation_delay=1000, animation_easing="elasticOut"
            )
        )
    )
    .add_xaxis(Faker.choose())
    .add_yaxis("商家A", Faker.values())
    .add_yaxis("商家B", Faker.values())
    .set_global_opts(title_opts=opts.TitleOpts(title="Bar-动画配置基本示例", subtitle="我是副标题"))
    .render("bar_base_with_animation.html")
)
```
