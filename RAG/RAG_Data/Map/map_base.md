---
图表类型: 地图 (Map)
功能标签: [地图, 地理数据, 省份数据, 可视化映射]
数据量级标签: small, medium
适用场景: 展示各省份或地区的数据分布，如全国各地区的销售数据、人口数据等。
数据适应: 适合带有地理信息的省份或城市数据。
美观要点: 清晰的地图、视觉映射组件、合适的颜色。
---

### 地图基本示例

这段代码展示了如何创建一个基本的地图，展示中国各省份的数据。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Map
from pyecharts.faker import Faker

c = (
    Map()
    .add("商家A", [list(z) for z in zip(Faker.provinces, Faker.values())], "china")
    .set_global_opts(title_opts=opts.TitleOpts(title="Map-基本示例"))
    .render("map_base.html")
)
```
