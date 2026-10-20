---
图表类型: 散点图 (Scatter)
功能标签: [散点图, 相关性, 分布, 数据点, 多系列]
数据量级标签: small, medium, large
适用场景: 观察两个数值变量之间的相关关系、聚集/离散程度，或按类别用多组散点对比
数据适应: x/y 均为数值；类别较多时用 add_yaxis 分组，避免单色混淆
美观要点: 控制 symbol_size 避免点重叠、必要时叠加视觉映射（VisualMap）与坐标轴缩放（DataZoom）
---

### 散点图基本示例

这段代码展示了如何创建一个基础散点图，用点展示两组数值之间的分布关系。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Scatter
from pyecharts.faker import Faker

c = (
    Scatter()
    .add_xaxis(Faker.choose())
    .add_yaxis("商家A", Faker.values())
    .set_global_opts(
        title_opts=opts.TitleOpts(title="Scatter-基本示例"),
        xaxis_opts=opts.AxisOpts(name="x 轴"),
        yaxis_opts=opts.AxisOpts(name="y 轴"),
        tooltip_opts=opts.TooltipOpts(trigger="item", formatter="{a} <br/>{b} : {c}"),
    )
    .render("scatter_base.html")
)
```

### 多系列散点图

多个系列使用不同颜色区分，适合按类别对比两组数据的分布差异。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Scatter
from pyecharts.faker import Faker

c = (
    Scatter()
    .add_xaxis(Faker.choose())
    .add_yaxis("商家A", Faker.values())
    .add_yaxis("商家B", Faker.values())
    .set_global_opts(
        title_opts=opts.TitleOpts(title="Scatter-多系列示例"),
        legend_opts=opts.LegendOpts(pos_bottom="0%"),
        xaxis_opts=opts.AxisOpts(name="x 轴"),
        yaxis_opts=opts.AxisOpts(name="y 轴"),
    )
    .render("scatter_multi.html")
)
```

### 使用要点

- 散点图 x/y 都应是数值列；类别列只用于分组（多系列）或提示信息。
- 数据点很多时可调小 `symbol_size`，或用 `EffectScatter` 强调关键点、用 `Scatter3D` 展示三维数据。
- 需要按数值大小上色时叠加 `opts.VisualMapOpts()`；坐标范围大时加 `opts.DataZoomOpts()`。
