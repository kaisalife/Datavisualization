---
图表类型: 地理坐标系特效散点图 (Geo EffectScatter)
功能标签: [地理坐标系, 特效散点, 动态效果]
数据量级标签: small, medium
适用场景: 突出显示关键地区的数据，增加视觉吸引力和关注度。
数据适应: 适合带有地理信息的数据。
美观要点: 特效散点、清晰的地图。
---

### 地理坐标系特效散点图

这段代码展示了如何创建地理坐标系的特效散点图，突出显示关键地区。

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
        type_=ChartType.EFFECT_SCATTER,
    )
    .set_series_opts(label_opts=opts.LabelOpts(is_show=False))
    .set_global_opts(title_opts=opts.TitleOpts(title="Geo-EffectScatter"))
    .render("geo_effectscatter.html")
)
```
