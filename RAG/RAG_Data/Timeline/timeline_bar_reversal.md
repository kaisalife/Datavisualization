---
图表类型: 时间轴横向柱状图 (Timeline-Bar-Reversal)
功能标签: [时间轴横向柱状图, 反转坐标轴, 右侧标签, 年份对比]
数据量级标签: small, medium
适用场景: 需要横向展示的多年度数据对比，标签在右侧展示。
数据适应: 多年度的同类数据，每年数据结构一致。
美观要点: 横向布局、标签位置合理、反转坐标轴、切换流畅。
---

### 时间轴横向柱状图

这段代码展示了如何创建一个时间轴横向柱状图，标签显示在右侧。

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
        .add_yaxis("商家A", Faker.values(), label_opts=opts.LabelOpts(position="right"))
        .add_yaxis("商家B", Faker.values(), label_opts=opts.LabelOpts(position="right"))
        .reversal_axis()
        .set_global_opts(
            title_opts=opts.TitleOpts("Timeline-Bar-Reversal (时间: {} 年)".format(i))
        )
    )
    tl.add(bar, "{}年".format(i))
tl.render("timeline_bar_reversal.html")
```
