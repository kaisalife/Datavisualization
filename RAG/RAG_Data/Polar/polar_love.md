---
图表类型: 极坐标系 (Polar)
功能标签: [心形曲线, 数学曲线, 数据可视化艺术, 时间轴
数据量级标签: large
适用场景: 数据可视化艺术展示、特殊形状数据展示、情人节主题。
数据适应: 数学函数生成的数据点，适合展示特殊形状。
美观要点: 心形明显、曲线流畅、时间轴清晰。
---

### 极坐标心形曲线图

这段代码展示了如何使用极坐标系展示心形曲线，适合数据可视化艺术和特殊主题展示。

#### 代码
```python
import math

from pyecharts import options as opts
from pyecharts.charts import Polar

data = []
for i in range(101):
    theta = i / 100 * 360
    r = 5 * (1 + math.sin(theta / 180 * math.pi))
    data.append([r, theta])
hour = [i for i in range(1, 25)]
c = (
    Polar()
    .add_schema(
        angleaxis_opts=opts.AngleAxisOpts(
            data=hour,
            type_="value",
            boundary_gap=False,
            start_angle=0,
            split_number=12,
            is_clockwise=True,
        )
    )
    .add("love", data, label_opts=opts.LabelOpts(is_show=False))
    .set_global_opts(title_opts=opts.TitleOpts(title="Polar-Love"))
    .render("polar_love.html")
)
```
