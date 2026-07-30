---
图表类型: 仪表盘 (Gauge)
功能标签: [仪表盘, 标题字体, 自定义样式]
数据量级标签: small
适用场景: 需要自定义仪表盘标题字体样式的场景。
数据适应: 适合展示单个百分比数据。
美观要点: 自定义标题字体、清晰的刻度。
---

### 自定义标题字体仪表盘

这段代码展示了如何创建自定义标题字体的仪表盘。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Gauge

c = (
    Gauge()
    .add(
        "",
        [("完成率", 66.6)],
        title_label_opts=opts.LabelOpts(
            font_size=40, color="blue", font_family="Microsoft YaHei"
        ),
    )
    .set_global_opts(title_opts=opts.TitleOpts(title="Gauge-改变轮盘内的字体"))
    .render("gauge_label_title_setting.html")
)
```
