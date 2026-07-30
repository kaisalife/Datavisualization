---
图表类型: 日历图 (Calendar)
功能标签: [热力图, 连续视觉映射, 隐藏年份标签, 自定义布局]
数据量级标签: medium
适用场景: 展示全年每日数据的热力图效果，如温度变化、活跃度等。
数据适应: 适合365天的全年数据，连续数据范围。
美观要点: 使用连续视觉映射，隐藏年份标签，简洁的布局。
---

### 日历热力图示例

这段代码展示了如何创建日历热力图，使用连续的视觉映射效果。

#### 代码
```python
import random
import datetime

import pyecharts.options as opts
from pyecharts.charts import Calendar


begin = datetime.date(2017, 1, 1)
end = datetime.date(2017, 12, 31)
data = [
    [str(begin + datetime.timedelta(days=i)), random.randint(1000, 25000)]
    for i in range((end - begin).days + 1)
]

(
    Calendar()
    .add(
        series_name="",
        yaxis_data=data,
        calendar_opts=opts.CalendarOpts(
            pos_top="120",
            pos_left="30",
            pos_right="30",
            range_="2017",
            yearlabel_opts=opts.CalendarYearLabelOpts(is_show=False),
        ),
    )
    .set_global_opts(
        title_opts=opts.TitleOpts(pos_top="30", pos_left="center", title="2017年步数情况"),
        visualmap_opts=opts.VisualMapOpts(
            max_=20000, min_=500, orient="horizontal", is_piecewise=False
        ),
    )
    .render("calendar_heatmap.html")
)
```
