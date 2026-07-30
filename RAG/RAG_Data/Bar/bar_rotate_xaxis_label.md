---
图表类型: 柱状图 (Bar)
功能标签: [标签旋转, 长标签, 坐标轴配置]
数据量级标签: small, medium
适用场景: 类别名称较长时的展示。
数据适应: 适合X轴标签较长，需要旋转避免重叠的场景。
美观要点: 标签旋转、避免拥挤、清晰可读。
---

### Bar-旋转X轴标签

这段代码展示了如何旋转X轴标签，解决标签名称过长导致重叠的问题。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Bar

c = (
    Bar()
    .add_xaxis(
        [
            "名字很长的X轴标签1",
            "名字很长的X轴标签2",
            "名字很长的X轴标签3",
            "名字很长的X轴标签4",
            "名字很长的X轴标签5",
            "名字很长的X轴标签6",
        ]
    )
    .add_yaxis("商家A", [10, 20, 30, 40, 50, 40])
    .add_yaxis("商家B", [20, 10, 40, 30, 40, 50])
    .set_global_opts(
        xaxis_opts=opts.AxisOpts(axislabel_opts=opts.LabelOpts(rotate=-15)),
        title_opts=opts.TitleOpts(title="Bar-旋转X轴标签", subtitle="解决标签名字过长的问题"),
    )
    .render("bar_rotate_xaxis_label.html")
)
```
