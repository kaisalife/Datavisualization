---
name: gauge-kpi-snapshot
title: 单指标达标仪表盘（KPI 快照）
description: 单个机组/设备/门店的达标率、完成率、利用率等单值 KPI —— Gauge 仪表盘 + 阈值配色，突出"是否达标"
chart_types: [Gauge]
min_rows: 1
user_keywords: [达标, 达标率, 完成率, 达成率, 完成情况, 仪表盘, 仪表, KPI, 利用率,
  负荷率, 水位, 目标完成, 考核, 达成情况]
require_keywords: true
---

# 单指标达标仪表盘（KPI 快照）

## 适用判断

- 用户问的是**一个对象的**一个状态值，并且关心"离目标还有多远"：机组发电量完成率、
  设备综合利用率、门店销售达成率、水库水位/负荷率、月度考核得分。
- 数据是"一行 = 一个对象一条考核记录"的宽表，完成率往往**不在数据里**，必须用
  实际值 ÷ 目标值换算——直接画"实际发电量"柱状图是口径错误。
- **只有在单对象/单指标时才用 Gauge**：
  - 用户点名一台机组 / 一个门店 → Gauge；
  - 用户要"全部机组/各门店对比" → Bar 排行，不要塞一排小仪表盘；
  - 多个指标（完成率 + 可用率 + 负荷率）→ 每个指标单独一张 Gauge（最多 4 张），
    **同一指标只留一张仪表盘**（不同指标可以多张）。
- 数据里没有目标值时不要硬做 Gauge（无法判断达标），改用数值对比图或在假设里写明。

## 数据加工范式

注入的 `df` 是接入层拆分后的表。宽表常见列：编号、装机容量、实际值、目标值、
停机时长。步骤固定：

```python
import pandas as pd

# 1) 定位用户点名的对象（编号可能有 0 前缀："03" / 3 / "3 号"）
unit_col = "机组编号"                  # 按实际列名改：设备编号/门店编号…
raw_unit = str(row_label)              # 用户话术里的对象，如 "03"
rows = df[df[unit_col].astype(str).str.zfill(2) == raw_unit.zfill(2)]
if rows.empty:
    rows = df[df[unit_col].astype(str) == raw_unit]
row = rows.iloc[0]

# 2) 换算完成率：目标值缺失或 <=0 时不要算（返回 None，让下游报错而不是给出 inf）
actual = pd.to_numeric(row["本月发电量(万kWh)"], errors="coerce")
target = pd.to_numeric(row["目标发电量(万kWh)"], errors="coerce")
value = None if pd.isna(target) or target <= 0 else round(float(actual) / float(target) * 100, 1)
```

- 只取一个对象、一个指标；装机容量、停机时长等冗余列不参与换算；
- 保留 1 位小数（96.0 就是 96.0，不要心算成 95/97）；
- 目标值列名可能是"目标发电量(万kWh)""月度目标""预算"，按实际列名取；
- 单位换算（万 kWh / 万元）不影响百分比，**分子分母同单位即可**，不要额外 ×10000。

## 生成要点

```python
import math
from pyecharts import options as opts
from pyecharts.charts import Gauge

# 超过 100% 时量程要跟着放大，否则指针顶在 100 处溢出
top = max(100, int(math.ceil(value / 10.0) * 10))
name = "3 号机组完成率"

gauge = (
    Gauge()
    .add(
        "",
        [(name, value)],
        min_=0,
        max_=top,
        split_number=5,
        radius="72%",
        axisline_opts=opts.AxisLineOpts(
            linestyle_opts=opts.LineStyleOpts(
                # 阈值按业务达标线定：低于 60% 红、60–85% 黄、85% 以上绿
                color=[(0.6, "#c23531"), (0.85, "#f2c94c"), (1.0, "#2ecc71")],
                width=18,
            )
        ),
        detail_label_opts=opts.LabelOpts(
            formatter="{value}%", font_size=30, position="center"
        ),
        title_label_opts=opts.LabelOpts(font_size=13),
    )
    .set_global_opts(
        title_opts=opts.TitleOpts(title="3 号机组发电量完成率（本月）"),
        tooltip_opts=opts.TooltipOpts(formatter="{b}: {c}%"),
    )
)
gauge.render()
```

- `Gauge.add` 的第二个参数是 `[(名称, 数值)]`，**数值必须是 number**，
  不要在值后面拼 `%`（百分号交给 `formatter`）；
- `min_`/`max_` 显式写；`max_` 至少 100，超过 100% 的完成率用 `ceil(value/10)*10`
  放大（如 106.9 → 110）；
- 阈值配色按业务来：达标线是 100% 时，红色段到 80%、黄色到 98%、绿色收尾；
  不要用默认单一颜色（用户看不出"未达标"）；
- 标题写清对象 + 期间 + 指标，不要只写"完成率"；
- 多个指标要出多张 Gauge 时，每张图独立 `render()`，不要在一个 Gauge 里塞多个
  series（指针会叠在一起，读数困难）。

## 踩坑点

- 完成率不能由模型"目测"：必须 `actual / target * 100`，并 `round(…, 1)`；
- 编号 `03` 当字符串处理时**保留前导 0**；`astype(str).str.zfill(2)` 同时兼容 3 / "03"；
- 用户说"全部机组"时改 Bar 排行（Gauge 只适合单值快照），这一点要在
  `assumptions` 里说明，而不是硬塞 8 个仪表盘；
- 目标值为 0 / 空时不要算百分比，输出明确错误；
- `Gauge` 是单指标图形：不要用它表达时间趋势或类目构成；
- 数据里同时有实际值和目标值两列时，**不要**把目标值也画成第二个 series。
