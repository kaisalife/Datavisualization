---
图表类型: 箱线图 (Boxplot)
功能标签: [基础箱线图, 数据分布, 多系列]
数据量级标签: small, medium
适用场景: 展示两组或多组实验数据的分布情况，如对比不同条件下的实验结果。
数据适应: 适合小到中等规模数据，每组约10-50个数据点。
美观要点: 清晰的箱体和须线，多系列时使用不同颜色区分。
---

### 基本箱线图示例

这段代码展示了如何创建基本的箱线图，用于对比两组实验数据的分布情况。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Boxplot

v1 = [
    [850, 740, 900, 1070, 930, 850, 950, 980, 980, 880, 1000, 980],
    [960, 940, 960, 940, 880, 800, 850, 880, 900, 840, 830, 790],
]
v2 = [
    [890, 810, 810, 820, 800, 770, 760, 740, 750, 760, 910, 920],
    [890, 840, 780, 810, 760, 810, 790, 810, 820, 850, 870, 870],
]
c = Boxplot()
c.add_xaxis(["expr1", "expr2"])
c.add_yaxis("A", c.prepare_data(v1))
c.add_yaxis("B", c.prepare_data(v2))
c.set_global_opts(title_opts=opts.TitleOpts(title="BoxPlot-基本示例"))
c.render("boxplot_base.html")
```
