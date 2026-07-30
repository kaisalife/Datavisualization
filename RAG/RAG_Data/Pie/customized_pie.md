---
图表类型: 饼图 (Pie)
功能标签: [自定义样式, 深色背景, 玫瑰图, 访问来源
数据量级标签: small
适用场景: 需要视觉效果突出的场景、深色主题展示、特殊风格的数据展示。
数据适应: 类别数 3-8 个，适合有特殊视觉要求的数据展示。
美观要点: 深色背景、玫瑰图效果、白色文字对比强烈、视觉冲击力强。
---

### 自定义样式深色背景饼图

这段代码展示了如何创建自定义样式的饼图，使用深色背景和玫瑰图效果，视觉效果突出，适合特殊场景的数据展示。

#### 代码
```python
import pyecharts.options as opts
from pyecharts.charts import Pie

x_data = ["直接访问", "邮件营销", "联盟广告", "视频广告", "搜索引擎"]
y_data = [335, 310, 274, 235, 400]
data_pair = [list(z) for z in zip(x_data, y_data)]
data_pair.sort(key=lambda x: x[1])

(
    Pie(init_opts=opts.InitOpts(bg_color="#2c343c"))
    .add(
        series_name="访问来源",
        data_pair=data_pair,
        rosetype="radius",
        radius="55%",
        center=["50%", "50%"],
        label_opts=opts.LabelOpts(is_show=False, position="center"),
    )
    .set_global_opts(
        title_opts=opts.TitleOpts(
            title="Customized Pie",
            pos_left="center",
            pos_top="20",
            title_textstyle_opts=opts.TextStyleOpts(color="#fff"),
        ),
        legend_opts=opts.LegendOpts(is_show=False),
    )
    .set_series_opts(
        tooltip_opts=opts.TooltipOpts(
            trigger="item", formatter="{a} <br/>{b}: {c} ({d}%)"
        ),
        label_opts=opts.LabelOpts(color="rgba(255, 255, 255, 0.3)"),
    )
    .render("customized_pie.html")
)
```
