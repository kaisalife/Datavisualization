---
图表类型: 自定义环形图 (Custom Doughnut)
功能标签: [环形图, 进度展示, 自定义图表, 分段显示]
数据量级标签: small
适用场景: 展示进度、完成度等环形分段图表，如任务完成进度、分数等。
数据适应: 分段数量 4-12 之间效果最佳，适合展示单个数值的分段环形图。
美观要点: 多个环形图布局合理，标签字体大小适中，颜色区分明确，悬停效果明显。
---

# 自定义环形图 (Custom Doughnut)

展示分段环形图的自定义图表，支持多个环形图同时展示。

## 示例代码

```python
from pyecharts import options as opts
from pyecharts.charts import Custom
from pyecharts.commons.utils import JsCode
from pyecharts.globals import ChartType


c = (
    Custom()
    .register_echarts_x(chart_type=ChartType.DOUGHNUT)
    .add(
        series_name="A",
        render_item=ChartType.DOUGHNUT,
        coordinate_system="none",
        item_payload_opts={
            "center": ["25%", "50%"],
            "radius": ["50%", "65%"],
            "segmentCount": 8,
            "label": {
                "show": True,
                "formatter": "{c}/{b}",
                "fontSize": 35,
                "color": "#555",
            }
        },
        data=[5],
        itemstyle_opts={},
        emphasis_opts=opts.EmphasisOpts(
            itemstyle_opts={
                "shadowBlur": 10,
                "shadowColor": "rgba(0, 0, 0, 0.2)",
            },
        )
    )
    .add(
        series_name="B",
        render_item=ChartType.DOUGHNUT,
        coordinate_system="none",
        item_payload_opts={
            "center": ["75%", "50%"],
            "radius": ["50%", "65%"],
            "segmentCount": 6,
            "label": {
                "show": True,
                "formatter": "{d} 🎉",
                "fontSize": 35,
                "color": "#555",
            }
        },
        data=[6],
        itemstyle_opts={},
        emphasis_opts=opts.EmphasisOpts(
            itemstyle_opts={
                "shadowBlur": 10,
                "shadowColor": "rgba(0, 0, 0, 0.2)",
            },
        )
    )
    .render("custom_doughnut.html")
)
```
