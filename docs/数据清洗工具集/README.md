# 数据视图层（DataView）：面向可视化的确定性数据变换

> 结论先行：截至 **2026-10-22**，没有现成的、专注"多模态数据清洗 + 图表准备"的 skill / MCP 工具集。
> 本项目采用的方案不是"清洗层"，而是一层**确定性数据视图（DataView）**：
> 每一次变换都是 `纯函数 × 不可变数据 → DataFrame`，结果可复现、可缓存、可审计；
> LLM 只出现在"写 spec"这一步，永远不在执行路径上。
>
> 历史备注：本目录早期版本提出过"图表契约（fitness / contract / strategy / variant）"分层方案，
> 已否决——多阶段流程太长、灵活性差；其后的"固定 op 清洗"方案也已否决——有限词表表达不了任意变换。
> 03/04/05/06 已按新方向重写；06 已删除。

## 一句话架构

```text
dataset（不可变，内容寻址）
   └── view = 纯变换（spec 可序列化：SQL 或纯函数插件）
         → view_id = hash(source_hash + spec_hash + engine_version)
         → 物化为 parquet，plan 只引用 view_id，生成代码只看 schema
```

- **数据层不认识 chart_type**。View 只返回「列名 + dtype + 行结构」，能不能画、怎么画是
  plan / 生成层的事。图表可行性检查留在生成代码里（`chart_data_check` 已有），不单设一层。
- **不新增流程阶段**。现有 `series` 路径保留：series 就是 view 的物化产物。
  用户没提特殊变换时直接走现状（0 次额外调用）；需要时 plan 多带一个 view spec，
  一次物化、多图复用。
- **默认不调 LLM**。同 `source + spec + engine_version` 必得同结果。

## 灵活性从哪来

唯一开放的是 **spec 的表达能力**，不是能力枚举：

1. `sql`：一条只读 `SELECT/WITH`（复用 `sql_safety.ensure_read_only` 校验）——
   聚合、透视、Top-N、排序、分箱、join 全覆盖；
2. `plugin`：注册过的纯函数 `def apply(df, params) -> df`（`plugins/data_view/` 每文件一个）——
   SQL 不擅长的领域变换（K 线重采样、模糊匹配、多模态后处理）。

新能力 = 新插件文件，核心零改动。**不是消灭函数，而是不让核心枚举能力**——
这就是对"硬编码灵活度不行"的回答。

## 硬原则

1. **不可变**：原始 dataset 只读；变换永远产出新 view，不覆盖；
2. **确定性**：spec 是纯的——无随机、无时间依赖、无 IO、无网络；插件的输入只有 `df` 和 `params`；
3. **短流程**：view 不是独立阶段，嵌在 plan 执行里；规划→生成链路不变；
4. **数据层与图表层解耦**：view 不知道图表类型；图表契约不进数据层，避免两者互相牵制。

## 目录

| 文件 | 内容 |
|---|---|
| [01-调研结论.md](01-调研结论.md) | 外部工具对比、为什么现成工具不够、不采用原因 |
| [02-工具清单.md](02-工具清单.md) | 已有能力盘点、待补能力、外部候选与依赖策略 |
| [03-数据视图设计.md](03-数据视图设计.md) | ViewSpec / 执行器 / 插件契约 / 确定性保证 / lineage |
| [04-MCP与暴露面.md](04-MCP与暴露面.md) | 怎么把 view 层暴露给 agent（最薄的两个工具）与安全边界 |
| [05-验收与落地计划.md](05-验收与落地计划.md) | P0/P1/P2 交付物、测试矩阵、验收标准 |

## 与现有代码的关系

接入层、归一化、series 拆分**全部保留且不重写**，它们本身就是"默认 view"的生产者：

- `service/data_ingestion/router.py` / `normalize.py`：接入 + 结构/值归一化（已有）；
- `service/data_ingestion/series/splitter.py` / `shape.py`：series 拆分与形态（已有，就是默认视图）；
- `service/data_ingestion/sql_safety.py`：只读 SQL 校验，view 执行器直接复用；
- `service/pipeline/chart_data_check.py`：渲染后检查（已有，是图表层的把关，不迁移到数据层）。

缺的只有一件事：**在 series 之上支持"声明式的派生视图"**，
即 `ViewSpec → 执行器 → 新 series（带 view_id）`。落地见 05。
