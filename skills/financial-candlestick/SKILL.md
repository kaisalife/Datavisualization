---
name: financial-candlestick
title: 金融 K 线 / OHLC
description: 开盘、最高、最低、收盘等金融行情：用 K 线保留价格区间，而不是四条折线
chart_types: [Candlestick]
user_keywords: [K线, K 线, 蜡烛图, 股票, 行情, 开盘, 收盘, OHLC, candlestick]
---

# 金融 K 线 / OHLC

## 适用判断
- 数据同时包含开盘、最高、最低、收盘（中英文列名都可能）。
- 用户明确要 K 线、蜡烛图、行情走势。
- 如果只有收盘价，普通 Line 就够，不要为了“像金融图”硬造 OHLC。

## 规划阶段
- `chart_type` 用 `Candlestick`，`analysis_task` 用 `trend`。
- `x_axis` 是时间列；`y_axis` 按 `[开盘, 收盘, 最低, 最高]` 的顺序列出四列。
- 成交量是辅助信息：可以在同一 plan 里说明，但不要默认把成交量塞进价格 y 轴。

## 生成阶段
1. 用 `from pyecharts.charts import Candlestick`，不要 import 不存在的类。
2. ECharts K 线数据顺序是 `[open, close, low, high]`，不是 `[open, high, low, close]`：
   ```python
   data = [
       [row["开盘"], row["收盘"], row["最低"], row["最高"]]
       for _, row in df.iterrows()
   ]
   ```
3. `add_xaxis(时间列表)`，`add_yaxis("价格", data)`。
4. 设置 `datazoom_opts=[opts.DataZoomOpts(type_="inside"), opts.DataZoomOpts(type_="slider")]`，
   方便用户放大某段行情。
5. y 轴写价格 + 单位；标题写清标的和时间范围。
6. 中国市场的常见配色是红涨绿跌；海外市场可能相反。用户没说明时保持默认或使用中性配色，
   并在 assumptions 里说明，不要擅自把颜色当成业务结论。
7. 数据很多时保留原始 K 线（K 线本身已经是聚合后的 OHLC），不要再按均值聚合价格。

## 可选：价格 + 成交量
- 用 `Grid` 上下布局：上方 70% K 线，下方 25% 成交量 Bar；两个子图共享时间轴。
- 成交量 Bar 用独立 y 轴，不要和价格共用刻度。
- 如果当前 pipeline 对 Grid 的双轴/共享轴支持不稳定，优先只画价格 K 线，保证正确性。
