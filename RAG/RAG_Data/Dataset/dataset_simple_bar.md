---
图表类型: 数据集柱状图 (Dataset Bar)
功能标签: [数据集管理, 多维度数据, 简化数据绑定]
数据量级标签: small, medium
适用场景: 展示多维度数据对比数据，如不同产品在不同年份的销量。
数据适应: 适合结构化的二维表数据，支持自动数据绑定。
美观要点: 清晰的坐标轴标签、图例、标题。
---

### 简单数据集柱状图示例

这段代码展示了如何使用 pyecharts 的 Dataset 功能来简化数据绑定，避免手动拆分数据。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Bar

c = (
    Bar()
    .add_dataset(
        source=[
            ["product", "2015", "2016", "2017"],
            ["Matcha Latte", 43.3, 85.8, 93.7],
            ["Milk Tea", 83.1, 73.4, 55.1],
            ["Cheese Cocoa", 86.4, 65.2, 82.5],
            ["Walnut Brownie", 72.4, 53.9, 39.1],
        ]
    )
    .add_yaxis(series_name="2015", y_axis=[])
    .add_yaxis(series_name="2016", y_axis=[])
    .add_yaxis(series_name="2017", y_axis=[])
    .set_global_opts(
        title_opts=opts.TitleOpts(title="Dataset simple bar example"),
        xaxis_opts=opts.AxisOpts(type_="category"),
    )
    .render("dataset_simple_bar.html")
)
```
