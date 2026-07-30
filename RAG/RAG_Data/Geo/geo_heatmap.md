---
图表类型: 地理坐标系热力图 (Geo HeatMap)
功能标签: [地理坐标系, 热力图, 密度分布]
数据量级标签: small, medium, large
适用场景: 展示数据的密度分布，如人口密度、销售热度等。
数据适应: 适合带有地理信息的数据。
美观要点: 热力图渐变、清晰的地图、视觉映射组件。
---

### 地理坐标系热力图

这段代码展示了如何创建地理坐标系的热力图，展示数据的密度分布。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Geo
from pyecharts.faker import Faker
from pyecharts.globals import ChartType

c = (
    Geo()
    .add_schema(maptype="china")
    .add(
        "geo",
        [list(z) for z in zip(Faker.provinces, Faker.values())],
        type_=ChartType.HEATMAP,
    )
    .set_series_opts(label_opts=opts.LabelOpts(is_show=False))
    .set_global_opts(
        visualmap_opts=opts.VisualMapOpts(),
        title_opts=opts.TitleOpts(title="Geo-HeatMap"),
    )
    .render("geo_heatmap.html")
)
```
