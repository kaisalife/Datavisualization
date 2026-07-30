---
图表类型: 时间轴多坐标轴 (Timeline-Multi-Axis)
功能标签: [时间轴柱状图, 多商家对比, 年份对比, 动态切换]
数据量级标签: small, medium
适用场景: 展示多年度多商家数据对比，如营业额对比、销售数据对比等。
数据适应: 多年度的多商家同类数据，每年数据结构一致。
美观要点: 多商家对比清晰、时间轴流畅、标题随年份变化。
---

### 时间轴多坐标轴柱状图

这段代码展示了如何创建一个时间轴多坐标轴柱状图，展示多商家多年度的营业额对比。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Bar, Timeline
from pyecharts.faker import Faker

tl = Timeline()
for i in range(2015, 2020):
    bar = (
        Bar()
        .add_xaxis(Faker.choose())
        .add_yaxis("商家A", Faker.values())
        .add_yaxis("商家B", Faker.values())
        .set_global_opts(title_opts=opts.TitleOpts("某商店{}年营业额".format(i)))
    )
    tl.add(bar, "{}年".format(i))
tl.render("timeline_multi_axis.html")
```
