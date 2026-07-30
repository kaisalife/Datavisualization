---
图表类型: 折线图 (Line)
功能标签: [堆叠面积图, 多系列, 总量展示, 填充效果]
数据量级标签: medium, large
适用场景: 展示多个数据系列的堆叠面积趋势，强调各部分占比和总量，如营销渠道数据等。
数据适应: 适合多个系列数据，需要展示总量和各部分的面积占比。
美观要点: 清晰的堆叠效果、合适的填充透明度、明确的图例、十字光标提示。
---

### 堆叠面积图

这段代码展示了如何创建一个堆叠面积图，用于展示多个数据系列的总量和各部分面积占比。

#### 代码
```python
import pyecharts.options as opts
from pyecharts.charts import Line

x_data = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
y_data = [820, 932, 901, 934, 1290, 1330, 1320]

(
    Line()
    .add_xaxis(xaxis_data=x_data)
    .add_yaxis(
        series_name="邮件营销",
        stack="总量",
        y_axis=[120, 132, 101, 134, 90, 230, 210],
        areastyle_opts=opts.AreaStyleOpts(opacity=0.5),
        label_opts=opts.LabelOpts(is_show=False),
    )
    .add_yaxis(
        series_name="联盟广告",
        stack="总量",
        y_axis=[220, 182, 191, 234, 290, 330, 310],
        areastyle_opts=opts.AreaStyleOpts(opacity=0.5),
        label_opts=opts.LabelOpts(is_show=False),
    )
    .add_yaxis(
        series_name="视频广告",
        stack="总量",
        y_axis=[150, 232, 201, 154, 190, 330, 410],
        areastyle_opts=opts.AreaStyleOpts(opacity=0.5),
        label_opts=opts.LabelOpts(is_show=False),
    )
    .add_yaxis(
        series_name="直接访问",
        stack="总量",
        y_axis=[320, 332, 301, 334, 390, 330, 320],
        areastyle_opts=opts.AreaStyleOpts(opacity=0.5),
        label_opts=opts.LabelOpts(is_show=False),
    )
    .add_yaxis(
        series_name="搜索引擎",
        stack="总量",
        y_axis=[820, 932, 901, 934, 1290, 1330, 1320],
        areastyle_opts=opts.AreaStyleOpts(opacity=0.5),
        label_opts=opts.LabelOpts(is_show=True, position="top"),
    )
    .set_global_opts(
        title_opts=opts.TitleOpts(title="堆叠区域图"),
        tooltip_opts=opts.TooltipOpts(trigger="axis", axis_pointer_type="cross"),
        yaxis_opts=opts.AxisOpts(
            type_="value",
            axistick_opts=opts.AxisTickOpts(is_show=True),
            splitline_opts=opts.SplitLineOpts(is_show=True),
        ),
        xaxis_opts=opts.AxisOpts(type_="category", boundary_gap=False),
    )
    .render("stacked_area_chart.html")
)
```
