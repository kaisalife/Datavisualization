---
图表类型: 雷达图 (Radar)
功能标签: [单选模式, 图例交互, 预算对比
数据量级标签: small
适用场景: 需要单独查看某组数据、多组数据交互展示。
数据适应: 维度数 4-8 个，数据组数 2-5 个，支持单选模式。
美观要点: 图例交互清晰、数据对比明确、颜色区分明显。
---

### 单选模式雷达图

这段代码展示了如何创建带单选模式的雷达图，用户可以通过图例单独查看每组数据。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Radar

v1 = [[4300, 10000, 28000, 35000, 50000, 19000]]
v2 = [[5000, 14000, 28000, 31000, 42000, 21000]]
c = (
    Radar()
    .add_schema(
        schema=[
            opts.RadarIndicatorItem(name="销售", max_=6500),
            opts.RadarIndicatorItem(name="管理", max_=16000),
            opts.RadarIndicatorItem(name="信息技术", max_=30000),
            opts.RadarIndicatorItem(name="客服", max_=38000),
            opts.RadarIndicatorItem(name="研发", max_=52000),
            opts.RadarIndicatorItem(name="市场", max_=25000),
        ]
    )
    .add("预算分配", v1)
    .add("实际开销", v2)
    .set_series_opts(label_opts=opts.LabelOpts(is_show=False))
    .set_global_opts(
        legend_opts=opts.LegendOpts(selected_mode="single"),
        title_opts=opts.TitleOpts(title="Radar-单例模式"),
    )
    .render("radar_selected_mode.html")
)
```
