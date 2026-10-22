---
name: data-view-usage
title: 数据视图（run_view）派生视角
description: 现有 series 没有用户要的视角（明细行需按月合计、重复项聚合、Top-N 过滤、拼接多表）时，用 describe_dataset + run_view 造一条派生数据系列，plan 引用它而不是在生成代码里现写 groupby
analysis_tasks: [aggregate, rank, filter, join, derive]
user_keywords: [按月合计, 按年合计, 汇总视图, 派生, 聚合, Top前N, 合计行, 明细行, 重复, 透视, 拼接, join]
---

# 数据视图（run_view）派生视角

## 适用判断（先看这条，避免滥用）

只在一个条件下使用：**现有 series 里没有用户想要的视角，而且不缺视角用户想要的图就出不来或不准确**。

典型场景：

- 用户上传的是明细长表（每行一笔记录），要求「按月合计 / 按城市汇总」——identity series 已被拆分为时间×类别的宽表或单系列，缺少明确的合计视角；
- 同一个键出现多行（多次测量、多轮记录），用户要的是聚合后的均值/总量；
- 只要 Top-N（如"销量前 10 的型号"），明细长表直接画会散；
- 需要把两张表按某个键拼接对齐（join）。

**不要用**的场景（这些不是数据问题，换个角度就解决）：

- 视角存在，只是你要换图表类型——plan 换类型即可，不要造重复数据；
- 负值想补成正数画饼图——数据井盖不了图意，改图型（换 Bar）；
- 只是想要"整理一下格式"——生成代码按现有 series 处理就够了。

## 规划阶段流程

1. `describe_dataset`：拿到表别名与列。默认表清单 =
   明细原始表 `table_0…`（数据预览时有）+ identity series `series_0…`；
2. `run_view`（mode=materialize）：提交一条 SQL，例如：

   ```sql
   -- 按月合计（明细 → 月度线）
   select 月份, sum(金额) as 金额 from table_0
   group by 月份 order by 月份

   -- Top-N 排行（重复项聚合）
   select 型号, sum(销量) as 销量 from table_0
   group by 型号 order by 销量 desc limit 10

   -- 两表每月对照（join）
   select a.月份, a.收入, b.支出 from table_0 a join table_1 b
     on a.月份 = b.月份 order by a.月份
   ```

3. 返回里带 `series_id` 列表——`create_plan` 直接引用（与普通 series 一致，
   plan 阶段照常校验、生成阶段照常注入 `df`，不需要任何新协议字段）；
4. `spec.title` 写一句语义名（如「按月合计」），它决定新系列的 display 名——
   规划日志和缓存 manifest 都靠它认路。

## 硬规则与易踩的坑

- **SQL 必须以只读 SELECT/WITH 收尾，且带 ORDER BY**：输出顺序不稳定会被
  `UNORDERED_OUTPUT` 拒绝；写操作（update/delete/多语句）立即被拒；
- ~输出 0 行会被 `EMPTY_RESULT` 拒绝~（这是质量守护而非噪音）：先 `describe_dataset`
  看样例值再写 WHERE，不是猜；
- 聚合口径要写进 plan 的 assumptions（如"跨时间聚合取均值"），和技能
  `high-frequency-timeseries` / `many-series-timeseries` 的口径约定一致；
- 同一 spec 重跑不重算（view_id 内容寻址，第二次直接命中缓存）；
- 一个任务最多造 1–2 条视图："为每个可能都造一条"是反模式，它把明细表
  拆散成碎片，并不比直接画明细图更有信息量。

## 生成阶段

不需要新增约定：run_view 产出的系列与 identity series 同构，注入的 `df`
就是变换后的表。所有正常的列校验、数据检查、polish 全部适用。
