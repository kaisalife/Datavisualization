---
name: pareto-quality
title: 帕累托 / 主次因素分析
description: 不良项、投诉原因、成本项等长尾分布排行：柱状图 + 累计占比双轴折线 + 80% 参考线
chart_types: [Bar]
analysis_tasks: [comparison]
require_keywords: true
user_keywords: [帕累托, 主次因素, 主要因素, 二八, 柏拉图, 不良, 缺陷, 不良项, 缺陷项,
  投诉原因, 停机原因, 故障原因, 排查, 质量问题, 质量异常, 不良率, 直通率下降,
  top不良, 主要原因, 关键因素]
---

# 帕累托 / 主次因素分析

## 适用判断

- 用户想回答"**少数几个类目占了大多数**"的问题：不良项、投诉原因、停机原因、
  成本构成项、退货原因、报障原因……都适用，不限于制造业。
- 数据常见形态是**业务事件日志**：每行一笔记录（发生日期、产线/渠道、类目描述、
  数量），需要自己聚合出"类目 → 总量"，再按总量**降序**排版。
- 类目通常 4–15 个、呈长尾（前 2–3 项占 60–80%）。全部均匀分布时帕累托没有
  信息量，普通 Bar 就够；类目超过 15 个时把最小尾部合并成"其他"（在 pandas
  里合并，保证占比总和仍是 100%）。
- 同义类目不要擅自合并（"划伤"与"表面划伤"可能是两类不良代码）；拿不准就在
  `ambiguities` 里列出让用户确认。

## 数据加工范式

事件日志经接入层拆分后，series 大多是**宽表**（行=日期，列=类目、值=数量）；
生成代码拿到的是注入的 `df`。两种形态都要会：

```python
# 情形一：宽表（时间 × 类目，接入层透视后的常见形态）
totals = (
    df.sum(axis=0, numeric_only=True)      # 每个类目列的总量
    .sort_values(ascending=False)
)
agg = pd.DataFrame({"类目": totals.index, "数量": totals.values})

# 情形二：长表（类目列 + 数量列还在同一行，groupby 聚合）
# agg = (
#     df.groupby("不良描述", as_index=False)["判定数量"].sum()
#     .sort_values("判定数量", ascending=False, ignore_index=True)
#     .rename(columns={"不良描述": "类目", "判定数量": "数量"})
# )

# 两情形之后是同一段：累计占比从聚合结果算，不在明细粒度上 cumsum
agg["累计占比"] = (agg["数量"].cumsum() / agg["数量"].sum() * 100).round(2)
```

- 计数场景（没有数量列、每行就是一笔）用 `df.sum(axis=0)`（宽表）或
  `groupby(...).size()`（长表）；
- 序号列（批次号/工单号）、备注列不进聚合；
- 合并"其他"类目时要放在**最后**一行，不要按数值排序挤进中间。

## 生成要点（双轴）

```python
from pyecharts import options as opts
from pyecharts.charts import Bar, Line

bar = (
    Bar()
    .add_xaxis(agg["类目"].tolist())
    .add_yaxis("数量", agg["数量"].tolist(), bar_max_width=42)
)
# 第二数值轴必须用 extend_axis：overlap(line) 会丢掉 line 图上
# set_global_opts(yaxis_opts=...) 设置的右轴（pyecharts 实测行为）
bar.extend_axis(
    yaxis=opts.AxisOpts(
        type_="value", name="累计占比（%）", min_=0, max_=100,
        axislabel_opts=opts.LabelOpts(formatter="{value}%"),
    )
)
line = (
    Line()
    .add_xaxis(agg["类目"].tolist())
    .add_yaxis(
        "累计占比",
        agg["累计占比"].tolist(),
        yaxis_index=1,
        is_symbol_show=False,
        markline_opts=opts.MarkLineOpts(
            data=[opts.MarkLineItem(y=80, name="80%")],
            linestyle_opts=opts.LineStyleOpts(type_="dashed"),
        ),
        label_opts=opts.LabelOpts(is_show=False),
    )
)
bar.overlap(line)
bar.set_global_opts(
    title_opts=opts.TitleOpts(title="缺陷类型主次因素排列"),
    yaxis_opts=opts.AxisOpts(name="数量"),
)
bar.render()
```

- 必须 `overlap`（同一坐标系叠加）而不是 `Grid`：帕累托是"一根轴上的两种度量"；
- 双轴：Bar 用左轴（数量），Line 用 `yaxis_index=1` 右轴（占比 0–100%）；
  右轴必须用 `bar.extend_axis(yaxis=opts.AxisOpts(...))` 创建——
  **不要**挂在 line 图上 set_global_opts，overlap 会把它吞掉（pyecharts 实测）；
  右轴轴名写"累计占比（%）"，轴标签带 `{value}%`；
- 80% 参考线："y=80 的目标线"挂在**占比 series** 上（add_yaxis 的 markline_opts
  参数），参考线落在右轴坐标系里；样式用虚线低饱和；
- 两个 x 轴类目列表**逐字相同、同一顺序**；Bar 降序，累计占比跟随 Bar 的顺序；- 生成代码按"df → agg → 双轴"三段组织，transform 过程写在代码里即可
  （`transform_hint` 注释也提示同样口径）。

## 踩坑点

- 累计占比必须从**聚合后**的数据算，不要在事件明细粒度上 cumsum；
- 占比数值保留 1–2 位小数；最后一个类目的累计占比必须正好是 100（浮点误差用
  `round(*, 2)` 处理，最后一位微差不改）；
- `chart_data_check` 允许 Bar+Line 双轴组合，不会因辅助层判偏离；
- 数量列可能是文本（"1,200"）——保持注入的 `df` 类型，pandas `sum()` 前
  不要重新解析，DataView/normalize 已处理；
- 类目顺序按数量降序后，不要被"其他"类目的数量打乱（"其他"永远在最后）。
