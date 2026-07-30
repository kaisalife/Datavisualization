---
图表类型: 平行坐标系 (Parallel)
功能标签: [多维度分析, 分类数据, 空气质量, 综合评价]
数据量级标签: medium
适用场景: 环境监测数据展示、综合质量评价、多指标对比分析。
数据适应: 样本数 10-50 个，维度数 5-12 个，支持分类维度进行分组。
美观要点: 不同分类使用不同颜色、坐标轴名称清晰、支持交互选择特定分类。
---

### 平行坐标系分类数据综合评价

这段代码展示了如何使用平行坐标系展示带有分类维度的多维度数据，特别适合空气质量监测、综合质量评价等场景。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Parallel

data = [
    [1, 91, 45, 125, 0.82, 34, 23, "良"],
    [2, 65, 27, 78, 0.86, 45, 29, "良"],
    [3, 83, 60, 84, 1.09, 73, 27, "良"],
    [4, 109, 81, 121, 1.28, 68, 51, "轻度污染"],
    [5, 106, 77, 114, 1.07, 55, 51, "轻度污染"],
    [6, 109, 81, 121, 1.28, 68, 51, "轻度污染"],
    [7, 106, 77, 114, 1.07, 55, 51, "轻度污染"],
    [8, 89, 65, 78, 0.86, 51, 26, "良"],
    [9, 53, 33, 47, 0.64, 50, 17, "良"],
    [10, 80, 55, 80, 1.01, 75, 24, "良"],
    [11, 117, 81, 124, 1.03, 45, 24, "轻度污染"],
    [12, 99, 71, 142, 1.1, 62, 42, "良"],
    [13, 95, 69, 130, 1.28, 74, 50, "良"],
    [14, 116, 87, 131, 1.47, 84, 40, "轻度污染"],
]
c = (
    Parallel()
    .add_schema(
        [
            opts.ParallelAxisOpts(dim=0, name="data"),
            opts.ParallelAxisOpts(dim=1, name="AQI"),
            opts.ParallelAxisOpts(dim=2, name="PM2.5"),
            opts.ParallelAxisOpts(dim=3, name="PM10"),
            opts.ParallelAxisOpts(dim=4, name="CO"),
            opts.ParallelAxisOpts(dim=5, name="NO2"),
            opts.ParallelAxisOpts(dim=6, name="CO2"),
            opts.ParallelAxisOpts(
                dim=7,
                name="等级",
                type_="category",
                data=["优", "良", "轻度污染", "中度污染", "重度污染", "严重污染"],
            ),
        ]
    )
    .add("parallel", data)
    .set_global_opts(title_opts=opts.TitleOpts(title="Parallel-Category"))
    .render("parallel_category.html")
)
```
