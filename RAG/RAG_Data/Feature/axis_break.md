# axisBreak 断轴（离群值场景，ECharts 6）

数值轴出现**一两个极端离群值**把大部分正常数据压扁成一条线时，用断轴
（axis breaks）把轴截断一段，正常数据波动立刻可见。

## 使用时机

- 数值范围跨度极大（如均线在 100–200，某个峰在 20000）且用户关心的是
  **多数数据的波动**而非那条离群值本身；
- 对数轴 `logBase` 也可解决跨度问题（值为正、且用户接受对数刻度）；
- 跨度小（10 倍以内）时优先 `is_scale=True` 非零基线，不要滥用断轴。

## 代码示例

```python
from pyecharts import options as opts
from pyecharts.charts import Line

chart = (
    Line()
    .add_xaxis(["1月", "2月", "3月"])
    .add_yaxis("销售额", [100, 200, 20000])
    .set_global_opts(
        title_opts=opts.TitleOpts(title="销售额（断轴处理大促峰值）"),
        yaxis_opts=opts.AxisOpts(
            type_="value",
            # axisbreaks_opts 是 AxisOpts 的参数；一段断轴用一个 AxisBreakOpts
            axisbreaks_opts=[opts.AxisBreakOpts(start=300, end=19000)],
        ),
    )
)
chart.render()
```

## 要点

- 断轴类在 `opts.AxisBreakOpts(start=..., end=...)`，挂在
  `opts.AxisOpts(axisbreaks_opts=[...])` 上（ECharts 6 能力，需要 v5 资产以上）；
- 只对 `type_="value"` 的数值轴有效；类目轴不能断；
- 断轴会破坏"柱高/面积与数值成正比"的直觉，**柱状图慎用**，折线/散点更合适；
- start/end 取"正常数据上沿"到"离群值下沿"之间，留少量空隙；
- 多个不连续离群段就给多个 AxisBreakOpts（一般不超过 2 段）。
