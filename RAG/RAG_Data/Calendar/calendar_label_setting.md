---
图表类型: 日历图 (Calendar)
功能标签: [中文标签, 自定义标签, 本地化, 分段式]
数据量级标签: medium
适用场景: 展示全年每日数据，需要中文标签的场景，如面向中文用户的数据展示。
数据适应: 适合365天的全年数据，每天一个数据点。
美观要点: 使用中文标签，清晰的分段式视觉映射。
---

### 中文标签日历图示例

这段代码展示了如何创建带有中文标签的日历图，提升中文用户的阅读体验。

#### 代码
```python
import datetime
import random

from pyecharts import options as opts
from pyecharts.charts import Calendar


begin = datetime.date(2017, 1, 1)
end = datetime.date(2017, 12, 31)
data = [
    [str(begin + datetime.timedelta(days=i)), random.randint(1000, 25000)]
    for i in range((end - begin).days + 1)
]

c = (
    Calendar()
    .add(
        "",
        data,
        calendar_opts=opts.CalendarOpts(
            range_="2017",
            daylabel_opts=opts.CalendarDayLabelOpts(name_map="cn"),
            monthlabel_opts=opts.CalendarMonthLabelOpts(name_map="cn"),
        ),
    )
    .set_global_opts(
        title_opts=opts.TitleOpts(title="Calendar-2017年微信步数情况(中文 Label)"),
        visualmap_opts=opts.VisualMapOpts(
            max_=20000,
            min_=500,
            orient="horizontal",
            is_piecewise=True,
            pos_top="230px",
            pos_left="100px",
        ),
    )
    .render("calendar_label_setting.html")
)
```
