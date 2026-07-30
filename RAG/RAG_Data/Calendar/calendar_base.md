---
图表类型: 日历图 (Calendar)
功能标签: [基础日历图, 时间序列, 视觉映射, 分段式]
数据量级标签: medium
适用场景: 展示全年每日数据分布，如微信步数、每日销售额、股票成交量等。
数据适应: 适合365天的全年数据，每天一个数据点。
美观要点: 使用分段式视觉映射，清晰的标题和图例位置。
---

### 基础日历图示例

这段代码展示了如何创建基础的日历图，用于展示全年每日数据的分布情况。

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
    .add("", data, calendar_opts=opts.CalendarOpts(range_="2017"))
    .set_global_opts(
        title_opts=opts.TitleOpts(title="Calendar-2017年微信步数情况"),
        visualmap_opts=opts.VisualMapOpts(
            max_=20000,
            min_=500,
            orient="horizontal",
            is_piecewise=True,
            pos_top="230px",
            pos_left="100px",
        ),
    )
    .render("calendar_base.html")
)
```
