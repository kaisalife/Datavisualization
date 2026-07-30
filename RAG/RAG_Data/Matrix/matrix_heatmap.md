---
图表类型: 矩阵热力图 (Matrix Heatmap)
功能标签: [矩阵热力图, 矩阵数据, 相关系数, 二维矩阵]
数据量级标签: medium, large
适用场景: 展示二维矩阵数据，如相关系数矩阵、相似度矩阵等。
数据适应: 适合二维方阵数据。
美观要点: 颜色渐变、清晰的标签、矩阵布局。
---

### 矩阵热力图示例

这段代码展示了如何创建一个矩阵热力图，展示二维矩阵数据。

#### 代码
```python
import random

from pyecharts import options as opts
from pyecharts.charts import HeatMap
from pyecharts.commons.utils import JsCode

xCnt = 8
yCnt = xCnt

xData = [{"value": f"X{i+1}"} for i in range(xCnt)]
yData = [{"value": f"Y{i+1}"} for i in range(yCnt)]

data = []
for i in range(1, xCnt + 1):
    for j in range(1, yCnt + 1):
        if i >= j:
            value = 1 if i == j else random.random() * 2 - 1
            data.append([f"X{i}", f"Y{j}", value])


c = (
    HeatMap()
    .add_xaxis(xaxis_data=xData)
    .add_yaxis(
        series_name="test",
        yaxis_data=yData,
        value=data,
        coordinate_system="matrix",
        label_opts=opts.LabelOpts(
            is_show=True,
            formatter=JsCode("(params) => params.value[2].toFixed(2)")
        ),
    )
    .set_global_opts(
        visualmap_opts=opts.VisualMapOpts(
            type_="continuous",
            max_=1,
            min_=-1,
            dimension=2,
            is_calculable=True,
            orient="horizontal",
            pos_top=5,
            pos_left="center",
        ),
        matrix_opts=opts.MatrixOpts(
            x_data=opts.MatrixAxisOpts(data=xData),
            y_data=opts.MatrixAxisOpts(data=yData),
            pos_top=80,
        ),
        legend_opts=opts.LegendOpts(is_show=False),
        xaxis_opts=opts.AxisOpts(is_show=False),
        yaxis_opts=opts.AxisOpts(is_show=False),
    )
)

c.render("matrix_heatmap.html")
```
