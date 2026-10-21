---
name: many-series-timeseries
title: 多设备/多指标时序
description: 车间设备、传感器阵列等宽表：先选 Top-N 或分组，避免上千条线挤在一张图
chart_types: [Line, Area, Bar]
time_like: true
min_series: 8
user_keywords: [设备, 传感器, 多指标, 多系列, 车间, 产线]
---

# 多设备/多指标时序

## 适用判断
- 时间序列的指标列很多（设备、传感器、产线），一次画全会变成“彩虹面条”。
- 用户更多关心整体趋势、异常设备或 Top-N，而不是每条线的每个点。

## 规划阶段
- 先决定“选哪些系列”，再决定图：
  - 用户点名了设备/指标：只选这些；
  - 用户要“全部”但列很多：按业务重要性、均值、波动/异常程度选 Top 8；
  - 需要看整体分布：考虑先聚合为分组（产线/区域）或改用 Heatmap。
- 在 assumptions 里写明选择规则，例如“按平均产量取前 8 台设备”。
- `y_axis` 不要超过 8–12 列；图例放底部，必要时用滚动图例。

## 生成阶段
1. 选列逻辑写在代码里，不要靠肉眼写死设备名：
   ```python
   numeric_cols = [c for c in df.columns if c != "时间"]
   top_cols = df[numeric_cols].mean().sort_values(ascending=False).head(8).index.tolist()
   ```
   如果业务上“波动大”更重要，就按 `std()` 或异常分数排序；在副标题说明排序依据。
2. 多系列折线：
   - `is_symbol_show=False`，线宽 1–2；
   - 图例用 `opts.LegendOpts(type_="scroll", pos_bottom="2%", pos_left="center")`；
   - 标签默认关闭，靠 tooltip 读数；
   - 同一张图超过 8–10 条线时，优先拆成 2 张图或改成 Top-N + 分组汇总。
3. 不同量纲的指标不要共用 y 轴；必要时拆图或归一化，并在标题/副标题说明。
4. 高频数据先按 `high-frequency-timeseries` 技能聚合，再选 Top-N。

## 不要做
- 不要生成上千个 legend 项和上千条 series；浏览器和图例都会失控。
- 不要只画“平均值”而隐藏设备间差异；需要时同时展示分布或异常点。
- 不要在没有说明的情况下删除设备/指标，选择规则要写进 assumptions 或副标题。
