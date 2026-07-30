---
图表类型: 饼图 (Pie)
功能标签:  [环形图, 访问来源, 流量分析
数据量级标签: small
适用场景: 网站流量分析、用户来源分析、需要展示外层空间的场景。
数据适应: 类别数 2-8 个，中间留白可以添加文字或其他元素。
美观要点: 环形宽度适中、颜色搭配和谐、标签清晰、中间有设计感。
---

### 环形图流量来源分析

这段代码展示了如何创建环形图（甜甜圈图），中间留白可以用于添加文字或其他设计元素，适合流量分析等场景。

#### 代码
```python
import pyecharts.options as opts
from pyecharts.charts import Pie

x_data = ["直接访问", "邮件营销", "联盟广告", "视频广告", "搜索引擎"]
y_data = [335, 310, 234, 135, 1548]

(
    Pie()
    .add(
        series_name="访问来源",
        data_pair=[list(z) for z in zip(x_data, y_data)],
        radius=["50%", "70%"],
        label_opts=opts.LabelOpts(is_show=False, position="center"),
    )
    .set_global_opts(legend_opts=opts.LegendOpts(pos_left="legft", orient="vertical"))
    .set_series_opts(
        tooltip_opts=opts.TooltipOpts(
            trigger="item", formatter="{a} <br/>{b}: {c} ({d}%)"
        ),
    )
    .render("doughnut_chart.html")
)
```
