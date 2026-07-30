---
图表类型: 时间轴地图 (Timeline-Map)
功能标签: [时间轴地图, 省份数据, 视觉映射, 多年度对比]
数据量级标签: medium, large
适用场景: 展示多年度各省份数据对比，如经济数据、人口数据等。
数据适应: 多年度的省份数据，每年数据结构一致。
美观要点: 地图颜色渐变、视觉映射清晰、年份切换流畅、标题随年份变化。
---

### 时间轴地图

这段代码展示了如何创建一个时间轴地图，展示多年度各省份的数据对比。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Map, Timeline
from pyecharts.faker import Faker

tl = Timeline()
for i in range(2015, 2020):
    map0 = (
        Map()
        .add("商家A", [list(z) for z in zip(Faker.provinces, Faker.values())], "china")
        .set_global_opts(
            title_opts=opts.TitleOpts(title="Map-{}年某些数据".format(i)),
            visualmap_opts=opts.VisualMapOpts(max_=200),
        )
    )
    tl.add(map0, "{}年".format(i))
tl.render("timeline_map.html")
```
