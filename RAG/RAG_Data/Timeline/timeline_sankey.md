---
图表类型: 时间轴桑基图 (Timeline-Sankey)
功能标签: [时间轴桑基图, 流量关系, 商家数据, 多年度对比]
数据量级标签: small, medium
适用场景: 展示多年度桑基图数据对比，如资金流向、物料流转等。
数据适应: 多年度的桑基图数据，节点固定，流量变化。
美观要点: 桑基图样式统一、曲线柔和、年份切换流畅。
---

### 时间轴桑基图

这段代码展示了如何创建一个时间轴桑基图，展示多年度商家之间的营业额差流量关系。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Sankey, Timeline
from pyecharts.faker import Faker

tl = Timeline()
names = ("商家A", "商家B", "商家C")
nodes = [{"name": name} for name in names]
for i in range(2015, 2020):
    links = [
        {"source": names[0], "target": names[1], "value": Faker.values()[0]},
        {"source": names[1], "target": names[2], "value": Faker.values()[0]},
    ]
    sankey = (
        Sankey()
        .add(
            "sankey",
            nodes,
            links,
            linestyle_opt=opts.LineStyleOpts(opacity=0.2, curve=0.5, color="source"),
            label_opts=opts.LabelOpts(position="right"),
        )
        .set_global_opts(
            title_opts=opts.TitleOpts(title="{}年商店（A, B, C）营业额差".format(i))
        )
    )
    tl.add(sankey, "{}年".format(i))
tl.render("timeline_sankey.html")
```
