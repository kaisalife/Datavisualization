---
图表类型: 折线图 (Line)
功能标签: [趋势展示, 大数据量, 采样, 缩放]
数据量级标签: large, huge
适用场景: 展示长时间序列数据（如每日销售额、股票价格）。
数据适应: 数据点 > 200 时建议使用采样和缩放。
美观要点: 平滑曲线、颜色渐变、可交互缩放。
---

### 带采样与缩放的大数据量折线图

这段代码展示了如何优雅地展示 365 天的数据，避免性能问题和视觉混乱。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Line
import random

# 生成模拟数据：365天的随机数值
days = [f"Day-{i}" for i in range(1, 366)]
values = [random.randint(50, 150) for _ in range(365)]

def create_large_line_chart(x_data, y_data):
    c = (
        Line(init_opts=opts.InitOpts(
            width="1400px",          // 加大画布宽度，适应多数据点
            height="600px",
            bg_color="#F5F5F5"
        ))
        .add_xaxis(xaxis_data=x_data)
        .add_yaxis(
            series_name="销售额",
            y_axis=y_data,
            is_smooth=True,          // 平滑曲线，提升视觉体验
            symbol="circle",
            symbol_size=4,            // 数据量大时适当减小点的大小
            linestyle_opts=opts.LineStyleOpts(width=2, color="#5793f3"),
            areastyle_opts=opts.AreaStyleOpts(opacity=0.3, color="#5793f3"),
            # 使用 LTTB 采样，在保留趋势的前提下减少渲染点，提升性能
            sampling="lttb",
            # 渐进式渲染（适用于大量数据）
            progressive=200,          // 每批渲染200个点
            progressive_threshold=500, // 超过500点启用渐进式渲染
        )
        .set_global_opts(
            title_opts=opts.TitleOpts(title="全年销售额趋势", subtitle="数据点: 365"),
            tooltip_opts=opts.TooltipOpts(trigger="axis", axis_pointer_type="cross"),
            # 数据缩放组件，允许用户自由查看局部细节
            datazoom_opts=[
                opts.DataZoomOpts(type_="inside", range_start=0, range_end=100),
                opts.DataZoomOpts(type_="slider", range_start=0, range_end=100),
            ],
            xaxis_opts=opts.AxisOpts(
                type_="category",
                name="日期",
                # 标签旋转，避免拥挤（因为数据点密集）
                axislabel_opts=opts.LabelOpts(rotate=45, interval=10),  // 每10个显示一个
                axistick_opts=opts.AxisTickOpts(is_align_with_label=True),
            ),
            yaxis_opts=opts.AxisOpts(name="销售额 (万元)"),
            legend_opts=opts.LegendOpts(pos_top="5%"),
        )
    )
    return c

# 生成并保存
chart = create_large_line_chart(days, values)
chart.render("large_line_chart.html")