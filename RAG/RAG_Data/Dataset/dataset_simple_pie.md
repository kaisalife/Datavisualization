---
图表类型: 数据集饼图 (Dataset Pie)
功能标签: [数据集管理, 多饼图布局, 数据编码]
数据量级标签: small, medium
适用场景: 展示多个年份的产品数据对比，使用多个饼图布局。
数据适应: 适合包含多个时间维度的数据表数据。
美观要点: 清晰的图例、合理的饼图位置布局。
---

### 简单数据集饼图示例

这段代码展示了如何使用 Dataset 和 encode 来创建多个饼图布局。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Pie

c = (
    Pie()
    .add_dataset(
        source=[
            ["product", "2012", "2013", "2014", "2015", "2016", "2017"],
            ["Matcha Latte", 41.1, 30.4, 65.1, 53.3, 83.8, 98.7],
            ["Milk Tea", 86.5, 92.1, 85.7, 83.1, 73.4, 55.1],
            ["Cheese Cocoa", 24.1, 67.2, 79.5, 86.4, 65.2, 82.5],
            ["Walnut Brownie", 55.2, 67.1, 69.2, 72.4, 53.9, 39.1],
        ]
    )
    .add(
        series_name="Matcha Latte",
        data_pair=[],
        radius=60,
        center=["25%", "30%"],
        encode={"itemName": "product", "value": "2012"},
    )
    .add(
        series_name="Milk Tea",
        data_pair=[],
        radius=60,
        center=["75%", "30%"],
        encode={"itemName": "product", "value": "2013"},
    )
    .add(
        series_name="Cheese Cocoa",
        data_pair=[],
        radius=60,
        center=["25%", "75%"],
        encode={"itemName": "product", "value": "2014"},
    )
    .add(
        series_name="Walnut Brownie",
        data_pair=[],
        radius=60,
        center=["75%", "75%"],
        encode={"itemName": "product", "value": "2015"},
    )
    .set_global_opts(
        title_opts=opts.TitleOpts(title="Dataset simple pie example"),
        legend_opts=opts.LegendOpts(pos_left="30%", pos_top="2%"),
    )
    .render("dataset_simple_pie.html")
)
```
