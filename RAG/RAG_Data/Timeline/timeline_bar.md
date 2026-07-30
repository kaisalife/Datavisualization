---
图表类型: 时间轴柱状图 (Timeline-Bar)
功能标签: [时间轴柱状图, 年份对比, 商家数据, 动态切换]
数据量级标签: small, medium
适用场景: 展示多年度数据对比，如营业额变化、销售数据对比等。
数据适应: 多年度的同类数据，每年数据结构一致。
美观要点: 时间轴清晰、柱状图样式统一、切换流畅、标题随年份变化。
---

### 时间轴柱状图

这段代码展示了如何创建一个时间轴柱状图，展示某商店多年度的营业额对比数据。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Bar, Timeline
from pyecharts.faker import Faker

x = Faker.choose()
tl = Timeline()
for i in range(2015, 2020):
    bar = (
        Bar()
        .add_xaxis(x)
        .add_yaxis("商家A", Faker.values())
        .add_yaxis("商家B", Faker.values())
        .set_global_opts(title_opts=opts.TitleOpts("某商店{}年营业额".format(i)))
    )
    tl.add(bar, "{}年".format(i))
tl.render("timeline_bar.html")
```
