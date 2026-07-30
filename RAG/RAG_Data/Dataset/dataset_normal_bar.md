---
图表类型: 数据集柱状图 (Dataset Bar)
功能标签: [数据集管理, 数据编码, 视觉映射]
数据量级标签: small, medium
适用场景: 展示包含多个指标的综合数据，支持数据编码和视觉映射。
数据适应: 适合包含多个维度的数据表数据，支持encode进行数据编码。
美观要点: 视觉映射颜色渐变、清晰的坐标轴标签。
---

### 普通数据集柱状图示例

这段代码展示了如何使用 encode 进行数据编码，并结合视觉映射组件。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Bar

c = (
    Bar()
    .add_dataset(
        source=[
            ["score", "amount", "product"],
            [89.3, 58212, "Matcha Latte"],
            [57.1, 78254, "Milk Tea"],
            [74.4, 41032, "Cheese Cocoa"],
            [50.1, 12755, "Cheese Brownie"],
            [89.7, 20145, "Matcha Cocoa"],
            [68.1, 79146, "Tea"],
            [19.6, 91852, "Orange Juice"],
            [10.6, 101852, "Lemon Juice"],
            [32.7, 20112, "Walnut Brownie"],
        ]
    )
    .add_yaxis(
        series_name="",
        y_axis=[],
        encode={"x": "amount", "y": "product"},
        label_opts=opts.LabelOpts(is_show=False),
    )
    .set_global_opts(
        title_opts=opts.TitleOpts(title="Dataset normal bar example"),
        xaxis_opts=opts.AxisOpts(name="amount"),
        yaxis_opts=opts.AxisOpts(type_="category"),
        visualmap_opts=opts.VisualMapOpts(
            orient="horizontal",
            pos_left="center",
            min_=10,
            max_=100,
            range_text=["High Score", "Low Score"],
            dimension=0,
            range_color=["#D7DA8B", "#E15457"],
        ),
    )
    .render("dataset_normal_bar.html")
)
```
