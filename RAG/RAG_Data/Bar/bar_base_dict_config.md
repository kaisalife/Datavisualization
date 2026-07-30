---
图表类型: 柱状图 (Bar)
功能标签: [字典配置, 主题, MACARONS]
数据量级标签: small, medium
适用场景: 偏好使用字典方式配置图表的场景。
数据适应: 适合熟悉字典配置方式的开发者。
美观要点: MACARONS主题、字典配置方式。
---

### Bar-通过 dict 进行配置

这段代码展示了如何使用字典方式配置柱状图，并使用MACARONS主题。

#### 代码
```python
from pyecharts.charts import Bar
from pyecharts.faker import Faker
from pyecharts.globals import ThemeType

c = (
    Bar({"theme": ThemeType.MACARONS})
    .add_xaxis(Faker.choose())
    .add_yaxis("商家A", Faker.values())
    .add_yaxis("商家B", Faker.values())
    .set_global_opts(
        title_opts={"text": "Bar-通过 dict 进行配置", "subtext": "我也是通过 dict 进行配置的"}
    )
    .render("bar_base_dict_config.html")
)
```
