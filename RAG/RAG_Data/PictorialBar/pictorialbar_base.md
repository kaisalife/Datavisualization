---
图表类型: 象形柱状图 (PictorialBar)
功能标签: [可视化对比, 基础符号, 横向排列, 人口统计]
数据量级标签: medium
适用场景: 人口数量对比、地域数据展示、需要直观视觉效果的场景。
数据适应: 数据项 5-20 个，数值范围适中，适合横向比较。
美观要点: 简洁的坐标轴、清晰的标题、统一的符号风格、适当的符号大小。
---

### 基础象形柱状图数据对比

这段代码展示了如何使用基础符号（圆角矩形）来创建象形柱状图，适合展示人口数量、地域数据等需要直观对比的场景。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import PictorialBar
from pyecharts.globals import SymbolType

location = ["山西", "四川", "西藏", "北京", "上海", "内蒙古", "云南", "黑龙江", "广东", "福建"]
values = [13, 42, 67, 81, 86, 94, 166, 220, 249, 262]

c = (
    PictorialBar()
    .add_xaxis(location)
    .add_yaxis(
        "",
        values,
        label_opts=opts.LabelOpts(is_show=False),
        symbol_size=18,
        symbol_repeat="fixed",
        symbol_offset=[0, 0],
        is_symbol_clip=True,
        symbol=SymbolType.ROUND_RECT,
    )
    .reversal_axis()
    .set_global_opts(
        title_opts=opts.TitleOpts(title="PictorialBar-各省份人口数量（虚假数据）"),
        xaxis_opts=opts.AxisOpts(is_show=False),
        yaxis_opts=opts.AxisOpts(
            axistick_opts=opts.AxisTickOpts(is_show=False),
            axisline_opts=opts.AxisLineOpts(
                linestyle_opts=opts.LineStyleOpts(opacity=0)
            ),
        ),
    )
    .render("pictorialbar_base.html")
)
```
