---
图表类型: 地理坐标系 (Geo)
功能标签: [地理坐标系, 地图数据, 可视化映射]
数据量级标签: small, medium
适用场景: 展示各省份或城市的数据分布，如全国各地区的销售数据。
数据适应: 适合带有地理信息的数据。
美观要点: 清晰的地图、视觉映射组件、合适的颜色。
---

### 地理坐标系基本示例

这段代码展示了如何创建一个基本的地理坐标系图表，展示中国各省份的数据。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Geo
from pyecharts.faker import Faker

c = (
    Geo()
    .add_schema(maptype="china")
    .add("geo", [list(z) for z in zip(Faker.provinces, Faker.values())])
    .set_series_opts(label_opts=opts.LabelOpts(is_show=False))
    .set_global_opts(
        visualmap_opts=opts.VisualMapOpts(), title_opts=opts.TitleOpts(title="Geo-基本示例")
    )
    .render("geo_base.html")
)
```
