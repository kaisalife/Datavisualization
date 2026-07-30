---
图表类型: 平行坐标系 (Parallel)
功能标签: [多维度分析, 混合数据, 简单对比]
数据量级标签: small
适用场景: 展示和对比少量样本的多个维度特征，适合产品评价和样本分析。
数据适应: 样本数 3-10 个，维度数 3-8 个，支持数值和分类混合数据。
美观要点: 线条颜色区分、半透明效果避免重叠、坐标轴标签清晰。
---

### 基础平行坐标系多维度分析

这段代码展示了如何使用平行坐标系来展示和对比多个样本在不同维度上的表现，特别适合产品评价和样本分析场景。

#### 代码
```python
import pyecharts.options as opts
from pyecharts.charts import Parallel

parallel_axis = [
    {"dim": 0, "name": "Price"},
    {"dim": 1, "name": "Net Weight"},
    {"dim": 2, "name": "Amount"},
    {
        "dim": 3,
        "name": "Score",
        "type": "category",
        "data": ["Excellent", "Good", "OK", "Bad"],
    },
]

data = [[12.99, 100, 82, "Good"], [9.99, 80, 77, "OK"], [20, 120, 60, "Excellent"]]


(
    Parallel()
    .add_schema(schema=parallel_axis)
    .add(
        series_name="",
        data=data,
        linestyle_opts=opts.LineStyleOpts(width=4, opacity=0.5),
    )
    .render("basic_parallel.html")
)
```
