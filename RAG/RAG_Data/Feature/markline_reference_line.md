# markLine 参考线（目标线 / 均值线 / 预算线）

在折线、柱状、散点等直角坐标系图表上叠加一条水平/垂直参考线，用于表达
**目标值、预算线、均值线、警戒线**。不给数据加噪音图形，是表达"数据 vs 基准差距"的首选。

## 使用时机

- 用户提到"目标 / 预算 / 达标 / 均值 / 平均 / 警戒线 / 基准"时优先考虑；
- 一条 series 最多一两个 markLine，避免参考线过多喧宾夺主；
- 均值线用 `type_="average"` 让 ECharts 自动计算，不要自己算好再硬编码 y 值。

## 代码示例

```python
from pyecharts import options as opts
from pyecharts.charts import Bar

chart = (
    Bar()
    .add_xaxis(["1月", "2月", "3月", "4月"])
    .add_yaxis(
        "销售额",
        [120, 200, 150, 180],
        # 均值线 + 显式目标线：均值自动计算，目标显式给 y 值
        markline_opts=opts.MarkLineOpts(
            data=[
                opts.MarkLineItem(type_="average", name="均值"),
                opts.MarkLineItem(y=170, name="目标线"),
            ],
            # 虚线 + 灰色，与真实数据系列区分开
            linestyle_opts=opts.LineStyleOpts(type_="dashed", color="#999"),
        ),
    )
    .set_global_opts(title_opts=opts.TitleOpts(title="月度销售额与目标"))
)
chart.render()
```

## 要点

- `markline_opts` 是 `add_yaxis` 的参数（挂在 series 上），不是 `set_global_opts`；
- `MarkLineItem(type_="average")` / `type_="max"` / `type_="min"` 自动取统计值；
- 显式目标线用 `MarkLineItem(y=数值, name="目标线")`（单数据系列时 y 轴参考线最直观）；
- 参考线样式建议虚线 + 低饱和色，真实数据保持实线高亮；
- 参考线 name 会出现在 tooltip / 图例外的标签里，起名要业务化（"2024 目标"而非 "line1"）。
