---
图表类型: 地球仪 (MapGlobe)
功能标签: [地球仪, 世界地图, 全球数据, 全球可视化]
数据量级标签: small, medium
适用场景: 展示全球数据分布，如世界各国人口数据等。
数据适应: 适合带有全球地理信息的数据。
美观要点: 地球仪效果、颜色渐变、视觉映射组件。
---

### 地球仪基本示例

这段代码展示了如何创建一个基本的地球仪，展示世界各国人口数据。

#### 代码
```python
import pyecharts.options as opts
from pyecharts.charts import MapGlobe
from pyecharts.faker import POPULATION

data = [x for _, x in POPULATION[1:]]
low, high = min(data), max(data)

c = (
    MapGlobe()
    .add_schema()
    .add(
        maptype="world",
        series_name="World Population",
        data_pair=POPULATION[1:],
        is_map_symbol_show=False,
        label_opts=opts.LabelOpts(is_show=False),
    )
    .set_global_opts(
        visualmap_opts=opts.VisualMapOpts(
            min_=low,
            max_=high,
            range_text=["max", "min"],
            is_calculable=True,
            range_color=["lightskyblue", "yellow", "orangered"],
        )
    )
    .render("map_globe_base.html")
)
```
