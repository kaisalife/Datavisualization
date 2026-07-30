---
图表类型: 饼图 (Pie)
功能标签: [占比展示, 基础饼图, 比例分析
数据量级标签: small
适用场景: 展示数据占比、类别比例、简单的分类数据展示。
数据适应: 类别数 2-10 个，适合展示各部分占比总和为100%的数据。
美观要点: 颜色区分明显、标签清晰、标题简洁、比例标注准确。
---

### 基础饼图占比展示

这段代码展示了如何创建最基础的饼图，用于展示数据的占比和比例，适合简单的分类数据展示。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import Pie
from pyecharts.faker import Faker

c = (
    Pie()
    .add("", [list(z) for z in zip(Faker.choose(), Faker.values())])
    .set_global_opts(title_opts=opts.TitleOpts(title="Pie-基本示例"))
    .set_series_opts(label_opts=opts.LabelOpts(formatter="{b}: {c}"))
    .render("pie_base.html")
)
```
