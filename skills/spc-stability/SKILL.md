---
name: spc-stability
title: 过程稳定性 / SPC 控制图
description: 连续测量的单指标过程稳定性（良率、尺寸、面密度、温度、响应时间）：X-MR 控制限 + 超限点标注，判断"只是正常波动还是出现特殊原因"
chart_types: [Line]
analysis_tasks: [trend]
min_rows: 10
user_keywords: [控制图, 控制限, SPC, 稳定性, 稳不稳定, 过程能力, 波动, 超限, 超出控制,
  报警, 规格上下限, 工艺参数, 良率波动, 均值漂移, 连续测量]
require_keywords: true
---

# 过程稳定性 / SPC 控制图

## 适用判断

- 用户问的是"**这个过程稳不稳定 / 有没有异常波动**"，数据是同一对象按时间（或生产顺序）
  连续测量的**单个指标**：良率、直通率、尺寸、面密度、温度、压力、接口响应时间。
- 典型话术："这批产品尺寸稳不稳定""良率有没有超出控制限""这两周面密度波动正常吗"。
- 用 **X-MR（单值-移动极差）控制图**：每个时间点一个观测值，用移动极差估计过程波动。
- 不适用：
  - 多个对象/产线对比 → 分组 Boxplot 或按对象分图（一张图一套控制限，别混算）；
  - 一个时间点有多次重复测量（子组）→ 先按时间点取均值再画，或改用 X-bar/R；
  - 有明显趋势/季节性（如逐月增长）→ 3σ 限会把趋势判成异常，需在假设里说明，
    或改用滚动基线，**不要静默去趋势**。
- 数据点少于 10 个时控制限不可靠：照常画但要在 `assumptions` 里提示样本不足。

## 数据加工范式

控制限**必须用数据算**，不能用规格上下限代替（规格是客户要求，控制限是过程实际能力）。

```python
import numpy as np
import pandas as pd

value_col = "面密度(mg/cm2)"          # 按实际指标列名改
df = df.copy()
df[value_col] = pd.to_numeric(df[value_col], errors="coerce")

# 缺失值只从控制限计算里剔除，不插值、不补 0
work = df.dropna(subset=[value_col]).reset_index(drop=True)
values = work[value_col].astype(float)

# X-MR：CL = 均值；sigma 用移动极差均值 / d2（n=2 时 d2 = 1.128）
center = float(values.mean())
mr_bar = float(values.diff().abs().dropna().mean())
sigma = mr_bar / 1.128
ucl, lcl = center + 3 * sigma, center - 3 * sigma

y = [round(v, 3) for v in values.tolist()]
if "记录时间" in work.columns:
    x = work["记录时间"].astype(str).tolist()
else:
    x = [f"第{i + 1}次" for i in range(len(y))]

# 超限点：保留原值，不删除、不替换
outliers = [(x[i], y[i]) for i in range(len(y)) if y[i] > ucl or y[i] < lcl]

# 规格限（可选，仅当数据里确有规格列时）
spec_high = next((c for c in work.columns if "规格上限" in c or "上限" in c), None)
spec_low = next((c for c in work.columns if "规格下限" in c or "下限" in c), None)
```

- 同一时间点有多行时先 `groupby(时间)[value_col].mean()`，避免把重复测量当成多个观测；
- 多个指标只画用户问的那一个；不要把"规格上限/下限"当指标列画成折线；
- 控制限保留 3 位小数，图上标注 `UCL 20.171` 这类具体值，方便对账。

## 生成要点

```python
from pyecharts import options as opts
from pyecharts.charts import Line

mark_lines = [
    opts.MarkLineItem(y=round(ucl, 3), name=f"UCL {ucl:.3f}"),
    opts.MarkLineItem(y=round(center, 3), name=f"CL {center:.3f}"),
    opts.MarkLineItem(y=round(lcl, 3), name=f"LCL {lcl:.3f}"),
]

line = (
    Line()
    .add_xaxis(x)
    .add_yaxis(
        "面密度(mg/cm2)",
        y,
        is_symbol_show=True,
        symbol_size=7,
        markline_opts=opts.MarkLineOpts(
            data=mark_lines,
            linestyle_opts=opts.LineStyleOpts(type_="dashed"),
            label_opts=opts.LabelOpts(position="insideEndTop", font_size=10),
        ),
        markpoint_opts=opts.MarkPointOpts(
            data=[
                opts.MarkPointItem(name="超限", coord=[xi, yi], value=yi)
                for xi, yi in outliers
            ],
            symbol="pin",
            symbol_size=38,
        ),
        markarea_opts=(
            opts.MarkAreaOpts(
                data=[opts.MarkAreaItem(name="规格范围", y=[float(spec_low_value), float(spec_high_value)])],
                itemstyle_opts=opts.ItemStyleOpts(color="rgba(46, 204, 113, 0.08)"),
            )
            if spec_high and spec_low
            else None
        ),
    )
    .set_global_opts(
        title_opts=opts.TitleOpts(title="涂布一线 面密度控制图（X-MR）"),
        xaxis_opts=opts.AxisOpts(type_="category", name="记录时间"),
        yaxis_opts=opts.AxisOpts(type_="value", name="面密度（mg/cm2）", is_scale=True),
        tooltip_opts=opts.TooltipOpts(trigger="axis"),
    )
)
line.render()
```

- 纯折线 + `is_scale=True` 让 y 轴贴合数据波动（SPC 看的是波动，不是 0 基线）；
  注意 pyecharts 2.1 的参数名是 `is_scale`，写 `scale=True` 会 TypeError；
- 控制限用**虚线**（`type_="dashed"`），CL 与 UCL/LCL 名称写全；
- 超限点用 `markPoint` 钉在原始坐标上（`coord=[x 类目, y 值]`），
  不改变折线数据；`markArea` 只表达规格范围，不参与控制限计算；
- 图例只保留一条"指标"系列，参考线不要另建 series（否则图例多出 UCL/LCL）。

## 踩坑点

- **控制限 ≠ 规格限**：用 `规格上限` 当 UCL 是口径错误；规格限只能画成背景区/附加线；
- 超限点就是结论，**不能删掉或平滑**；也不要把超限点改成 null；
- 缺失值不插值（插值会人为降低波动、放宽控制限）；
- 每张图只算一套控制限：多产线/多设备要分开出图，混在一起算会掩盖单条线的漂移；
- 移动极差按"相邻有效观测"计算，缺一个点不影响后续差值，但要在数据里保留时间顺序；
- 观测值量级接近 0（如温度 0.02）时要保留足够小数位，`round(3)` 后再画，
  否则图上所有点看起来都在一条直线上；
- 不要给 SPC 图加 0 基线、不要用柱状图（柱状图会把波动藏在柱高里）；
- 图中不要出现第二套 y 轴（除非同时画极差 R 图，而那应另开一张图）。
