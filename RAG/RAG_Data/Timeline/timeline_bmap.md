---
图表类型: 时间轴百度地图 (Timeline-BMap)
功能标签: [时间轴百度地图, 热力图, 省份数据, 多年度对比]
数据量级标签: medium, large
适用场景: 展示多年度地理热力图数据对比，如人口密度、经济活跃度等。
数据适应: 多年度的省份地理数据，每年数据结构一致。
美观要点: 热力图效果明显、百度地图集成、时间轴位置合理、切换流畅。
---

### 时间轴百度地图热力图

这段代码展示了如何创建一个时间轴百度地图热力图，展示多年度各省份的热力数据对比。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import BMap, Timeline
from pyecharts.faker import Faker

tl = Timeline()
tl.add_schema(pos_left="50%", pos_right="10px", pos_bottom="15px")
for i in range(2015, 2020):
    bmap = (
        BMap()
        .add_schema(baidu_ak="FAKE_AK", center=[120.13066322374, 30.240018034923])
        .add(
            "bmap",
            [list(z) for z in zip(Faker.provinces, Faker.values())],
            type_="heatmap",
        )
        .set_global_opts(
            title_opts=opts.TitleOpts(title="Timeline-BMap-热力图-{}年".format(i)),
            visualmap_opts=opts.VisualMapOpts(pos_bottom="center", pos_right="10px"),
            tooltip_opts=opts.TooltipOpts(formatter=None),
        )
    )
    tl.add(bmap, "{}年".format(i))
tl.render("timeline_bmap.html")
```
