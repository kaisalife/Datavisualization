---
图表类型: 漏斗图 (Funnel)
功能标签: [漏斗图, 流程转化, 自定义样式, 提示框]
数据量级标签: small, medium
适用场景: 展示业务流程转化漏斗，如展现-点击-访问-咨询-订单等流程。
数据适应: 适合展示数据递减的流程数据。
美观要点: 自定义标签位置、自定义样式、清晰的提示框。
---

### 自定义漏斗图示例

这段代码展示了如何创建自定义样式的漏斗图，包括标签位置、间距、提示框等。

#### 代码
```python
import pyecharts.options as opts
from pyecharts.charts import Funnel

x_data = ["展现", "点击", "访问", "咨询", "订单"]
y_data = [100, 80, 60, 40, 20]

data = [[x_data[i], y_data[i]] for i in range(len(x_data))]

(
    Funnel()
    .add(
        series_name="",
        data_pair=data,
        gap=2,
        tooltip_opts=opts.TooltipOpts(trigger="item", formatter="{a} <br/>{b} : {c}%"),
        label_opts=opts.LabelOpts(is_show=True, position="inside"),
        itemstyle_opts=opts.ItemStyleOpts(border_color="#fff", border_width=1),
    )
    .set_global_opts(title_opts=opts.TitleOpts(title="漏斗图", subtitle="纯属虚构"))
    .render("funnel_chart.html")
)
```
