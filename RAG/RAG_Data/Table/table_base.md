---
图表类型: 表格 (Table)
功能标签: [基础表格, 数据展示, 标题设置, 副标题支持]
数据量级标签: small, medium
适用场景: 展示结构化数据，如城市信息、统计数据、报表数据等。
数据适应: 二维表格数据，包含表头和行数据。
美观要点: 表头清晰、数据对齐、标题简洁、排版整齐。
---

### 基础表格

这段代码展示了如何创建一个基础的表格组件，展示城市相关数据。

#### 代码
```python
from pyecharts.components import Table
from pyecharts.options import ComponentTitleOpts


table = Table()

headers = ["City name", "Area", "Population", "Annual Rainfall"]
rows = [
    ["Brisbane", 5905, 1857594, 1146.4],
    ["Adelaide", 1295, 1158259, 600.5],
    ["Darwin", 112, 120900, 1714.7],
    ["Hobart", 1357, 205556, 619.5],
    ["Sydney", 2058, 4336374, 1214.8],
    ["Melbourne", 1566, 3806092, 646.9],
    ["Perth", 5386, 1554769, 869.4],
]
table.add(headers, rows)
table.set_global_opts(
    title_opts=ComponentTitleOpts(title="Table-基本示例", subtitle="我是副标题支持换行哦")
)
table.render("table_base.html")
```
