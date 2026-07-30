---
图表类型: 弦图 (Chord)
功能标签: [关系展示, 节点连接, 权重可视化, 网络关系]
数据量级标签: small
适用场景: 展示实体之间的关系和连接强度，如社交网络、人物关系、系统模块关系等。
数据适应: 节点数量 5-20 之间效果最佳，每个节点与其他节点有一定的连接关系。
美观要点: 节点标签清晰，连线颜色对应目标节点，弦图布局美观，关系一目了然。
---

# 基础弦图 (Chord Base)

展示实体之间关系和连接强度的基础弦图。

## 示例代码

```python
from pyecharts import options as opts
from pyecharts.charts import Chord

c = (
    Chord()
    .add(
        series_name="chord",
        data=[
            opts.ChordData(name="A"),
            opts.ChordData(name="B"),
            opts.ChordData(name="C"),
            opts.ChordData(name="D"),
        ],
        links=[
            opts.ChordLink(source="A", target="B", value=40),
            opts.ChordLink(source="A", target="C", value=20),
            opts.ChordLink(source="B", target="D", value=20),
        ],
        is_clockwise=False,
        label_opts=opts.LabelOpts(is_show=True),
        linestyle_opts=opts.LineStyleOpts(color="target"),
    )
    .render("chord_base.html")
)
```
