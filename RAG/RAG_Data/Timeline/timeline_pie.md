---
图表类型: 时间轴饼图 (Timeline-Pie)
功能标签: [时间轴饼图, 玫瑰图, 年份对比, 商家数据]
数据量级标签: small, medium
适用场景: 展示多年度饼图数据对比，如营业额占比、市场份额等。
数据适应: 多年度的饼图数据，每年数据结构一致。
美观要点: 饼图样式统一、玫瑰图效果、年份切换流畅、标题随年份变化。
---

### 时间轴饼图

这段代码展示了如何创建一个时间轴饼图，展示多年度的玫瑰图数据对比。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Pie, Timeline
from pyecharts.faker import Faker

attr = Faker.choose()
tl = Timeline()
for i in range(2015, 2020):
    pie = (
        Pie()
        .add(
            "商家A",
            [list(z) for z in zip(attr, Faker.values())],
            rosetype="radius",
            radius=["30%", "55%"],
        )
        .set_global_opts(title_opts=opts.TitleOpts("某商店{}年营业额".format(i)))
    )
    tl.add(pie, "{}年".format(i))
tl.render("timeline_pie.html")
```
