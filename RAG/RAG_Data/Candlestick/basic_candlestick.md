---
图表类型: K线图 (Candlestick/Kline)
功能标签: [基础K线图, 金融数据, 开盘收盘, 最高最低]
数据量级标签: small
适用场景: 展示少量金融数据的K线图，如短期股票走势展示。
数据适应: 适合少量数据，每天一个K线数据（开盘、最高、最低、收盘）。
美观要点: 清晰的K线样式，合适的坐标轴分割线。
---

### 基础K线图示例

这段代码展示了如何创建基础的K线图，用于展示金融数据的开盘、最高、最低、收盘价格。

#### 代码
```python
import pyecharts.options as opts
from pyecharts.charts import Candlestick

x_data = ["2017-10-24", "2017-10-25", "2017-10-26", "2017-10-27"]
y_data = [[20, 30, 10, 35], [40, 35, 30, 55], [33, 38, 33, 40], [40, 40, 32, 42]]

(
    Candlestick()
    .add_xaxis(xaxis_data=x_data)
    .add_yaxis(series_name="", y_axis=y_data)
    .set_series_opts()
    .set_global_opts(
        yaxis_opts=opts.AxisOpts(
            splitline_opts=opts.SplitLineOpts(
                is_show=True, linestyle_opts=opts.LineStyleOpts(width=1)
            )
        )
    )
    .render("basic_candlestick.html")
)
```
