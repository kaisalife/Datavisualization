---
图表类型: 网格布局 (Grid)
功能标签: [网格布局, 多图组合, 水平布局, 数据对比]
数据量级标签: small, medium, large
适用场景: 将多个图表水平排列在一起，方便对比查看。
数据适应: 适合需要同时展示多个相关图表的场景。
美观要点: 合理的间距、清晰的标题、统一的风格。
---

### 水平网格布局示例

这段代码展示了如何使用Grid组件将散点图和折线图水平排列在一起。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Grid, Line, Scatter
from pyecharts.faker import Faker

scatter = (
    Scatter()
    .add_xaxis(Faker.choose())
    .add_yaxis("商家A", Faker.values())
    .add_yaxis("商家B", Faker.values())
    .set_global_opts(
        title_opts=opts.TitleOpts(title="Grid-Scatter"),
        legend_opts=opts.LegendOpts(pos_left="20%"),
    )
)
line = (
    Line()
    .add_xaxis(Faker.choose())
    .add_yaxis("商家A", Faker.values())
    .add_yaxis("商家B", Faker.values())
    .set_global_opts(
        title_opts=opts.TitleOpts(title="Grid-Line", pos_right="5%"),
        legend_opts=opts.LegendOpts(pos_right="20%"),
    )
)

grid = (
    Grid()
    .add(scatter, grid_opts=opts.GridOpts(pos_left="55%"))
    .add(line, grid_opts=opts.GridOpts(pos_right="55%"))
    .render("grid_horizontal.html")
)
```
