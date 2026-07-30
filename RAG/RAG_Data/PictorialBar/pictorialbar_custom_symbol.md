---
图表类型: 象形柱状图 (PictorialBar)
功能标签: [自定义符号, 视觉趣味, 横向排列, 个性化展示]
数据量级标签: medium
适用场景: 趣味数据展示、品牌形象展示、需要个性化符号的场景。
数据适应: 数据项 5-20 个，需要配套自定义符号资源文件。
美观要点: 符号与数据主题匹配、颜色协调、符号大小合适、标题有吸引力。
---

### 自定义符号象形柱状图

这段代码展示了如何使用自定义的SVG符号来创建象形柱状图，让数据展示更加有趣和个性化，适合趣味数据和品牌形象展示。

#### 代码
```python
import json

from pyecharts import options as opts
from pyecharts.charts import PictorialBar

location = ["山西", "四川", "西藏", "北京", "上海", "内蒙古", "云南", "黑龙江", "广东", "福建"]
values = [13, 42, 67, 81, 86, 94, 166, 220, 249, 262]


with open("symbol.json", "r", encoding="utf-8") as f:
    symbols = json.load(f)


c = (
    PictorialBar()
    .add_xaxis(location)
    .add_yaxis(
        "",
        values,
        label_opts=opts.LabelOpts(is_show=False),
        symbol_size=22,
        symbol_repeat="fixed",
        symbol_offset=[0, -5],
        is_symbol_clip=True,
        symbol=symbols["boy"],
    )
    .reversal_axis()
    .set_global_opts(
        title_opts=opts.TitleOpts(title="PictorialBar-自定义 Symbol"),
        xaxis_opts=opts.AxisOpts(is_show=False),
        yaxis_opts=opts.AxisOpts(
            axistick_opts=opts.AxisTickOpts(is_show=False),
            axisline_opts=opts.AxisLineOpts(
                linestyle_opts=opts.LineStyleOpts(opacity=0)
            ),
        ),
    )
    .render("pictorialbar_custom_symbol.html")
)
```
