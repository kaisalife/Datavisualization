---
图表类型: 词云图 (WordCloud)
功能标签: [文本可视化, 内置形状, 菱形]
数据量级标签: small, medium
适用场景: 需要简单几何形状的词云展示，如数据报告、简单装饰等。
数据适应: 需要词频统计数据，关键词数量建议20-100个。
美观要点: 合适的形状选择、词大小范围、颜色搭配。
---

### 菱形形状的词云图

这段代码展示了如何创建一个使用内置菱形形状的词云图。

#### 代码
```python
from pyecharts import options as opts
from pyecharts.charts import WordCloud
from pyecharts.globals import SymbolType

words = [
    ("Sam S Club", 10000),
    ("Macys", 6181),
    ("Amy Schumer", 4386),
    ("Jurassic World", 4055),
    ("Charter Communications", 2467),
    ("Chick Fil A", 2244),
    ("Planet Fitness", 1868),
    ("Pitch Perfect", 1484),
    ("Express", 1112),
    ("Home", 865),
    ("Johnny Depp", 847),
    ("Lena Dunham", 582),
    ("Lewis Hamilton", 555),
    ("KXAN", 550),
    ("Mary Ellen Mark", 462),
    ("Farrah Abraham", 366),
    ("Rita Ora", 360),
    ("Serena Williams", 282),
    ("NCAA baseball tournament", 273),
    ("Point Break", 265),
]

c = (
    WordCloud()
    .add("", words, word_size_range=[20, 100], shape=SymbolType.DIAMOND)
    .set_global_opts(title_opts=opts.TitleOpts(title="WordCloud-shape-diamond"))
    .render("wordcloud_diamond.html")
)
```
