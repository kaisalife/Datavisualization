# MCP 与 Skill 设计

## 1. 为什么要同时有 skill 和 MCP

- **Skill** 解决“什么时候做、按什么顺序做、哪些不能做”；
- **MCP** 解决“真正执行确定性操作”，让 agent 不需要自己写 pandas 代码；
- 两者分开，才能保证：
  - 规则可审计：每个动作来自明确的 tool + 参数；
  - 结果可复现：同一份数据 + 同一份计划 → 同一结果；
  - 模型可替换：换 LLM 不影响清洗逻辑；
  - 安全边界清晰：模型不能直接改文件、不能执行任意代码。

> 不建议把清洗规则全写进主 prompt，也不建议让 agent 用 `run_code` 临时写清洗代码。
> `run_code` 保留给图表生成/调试；数据清洗走专用工具。

## 2. Skill：`multimodal-data-cleaning`

### 2.1 建议位置

```text
skills/multimodal-data-cleaning/SKILL.md
```

### 2.2 frontmatter

现有 `service/skills/registry.py` 的匹配字段主要面向图表技能（`chart_types` / `analysis_tasks` /
`time_like` / `min_rows` / `min_series` / `user_keywords`）。清洗技能不应硬塞进图表匹配逻辑，
建议扩展 registry 支持 `capabilities` / `source_kinds`，或在数据接入阶段使用独立的 skill loader。

建议 frontmatter：

```yaml
---
name: multimodal-data-cleaning
title: 多模态表格清洗
description: 图片/PDF/Office/CSV/Excel 抽表后的表头、数值、缺失、重复、异常与单位检查；默认只报告，修改需确认
capabilities: [data_cleaning, data_quality, table_normalization]
source_kinds: [file, document, image, pdf, office, database, api]
user_keywords: [清洗, 脏数据, 缺失, 空值, 重复, 异常值, 单位, 表头, 合并单元格, 数据质量]
---
```

### 2.3 正文结构

```markdown
# 多模态表格清洗

## 适用判断
- 数据来自截图/PDF/Office 内嵌表格，或 CSV/Excel 表头明显不规整。
- 用户要求“清洗”“去重”“处理缺失”“检查数据质量”“统一单位”。
- 图表生成前发现列语义识别失败、数值列被当成文本、时间轴乱序。

## 工作流
1. 先调用 `profile_table`，不要直接改数据。
2. 调用 `detect_issues`，按 severity 汇报；不要只报“数据脏”。
3. 对 `error` 级问题先解决；对 `warn` 级问题给出建议。
4. 需要修改时，先 `apply_cleaning_plan(dry_run=true)`，展示将影响的行/列。
5. 得到用户确认后，再 `apply_cleaning_plan(dry_run=false)`。
6. 调用 `validate_table`，确认没有引入新的结构问题。
7. 最后才进入图表规划；在 assumptions 里写明清洗口径。

## 规则
- 列名保真：有表头就沿用，包括年份、单位、百分号；不要“美化”成业务名。
- 缺失值：默认只报告；不要用 0/均值填充，除非用户明确要求。
- 重复行：默认只报告；先确认是重复录入还是多批次真实记录。
- 异常值：默认只标记；不要自动删除。
- 单位：保留原单位；换算必须显式确认。
- 合计/小计：默认提示排除，不要混进类别比较。
- 多表：先确认主表；不要把不同表硬拼成一个 series。

## 不要做
- 不要用 LLM 生成缺失行、缺失列或“合理”的合计。
- 不要覆盖原始文件或原始表。
- 不要为了图表好看而删除不利的数据点。
- 不要把“来自图片”当成改变清洗规则的理由。
```

## 3. MCP Server：`data_cleaning`

### 3.1 形态

- 新增 `agent_tools/tool_data_cleaning.py`；
- 使用 `fastmcp`，stdio transport，与现有 `run_code` 一致；
- `configs/default_config.json` 增加：

```json
{
  "mcp_config": {
    "run_code": { "...": "..." },
    "data_cleaning": {
      "command": "python",
      "args": ["agent_tools/tool_data_cleaning.py"],
      "transport": "stdio"
    }
  }
}
```

- 是否默认启用由配置决定；清洗 skill 只在需要时加载，避免给普通图表任务增加上下文和启动成本。

### 3.2 状态模型

不要让 LLM 传整张 DataFrame 或文件路径。MCP 进程维护会话级状态：

```text
DatasetHandle
├── dataset_id   # 会话 ID，例如 ds_ab12cd34ef56
├── table_id     # 逻辑表名，例如 sales_2024
├── version      # 清洗版本，0 = 原始，1..n = 清洗后
└── artifacts    # parquet / report / preview 路径（只给服务端，不返回给 LLM）
```

所有工具只接受 `dataset_id` / `table_id` / `version` 和规则参数，返回摘要 + 问题列表 + 预览。
文件路径、原始数据、内部目录不进入 LLM 上下文。

### 3.3 工具契约

| 工具 | 作用 | 是否修改数据 | 关键参数 |
|---|---|---|---|
| `list_tables` | 列出会话内可用的表/版本 | 否 | `dataset_id` |
| `profile_table` | schema、行数、缺失率、唯一值、样例 | 否 | `dataset_id`, `table_id`, `version` |
| `detect_issues` | 按规则检查质量问题 | 否 | `checks`（可选，默认全部） |
| `normalize_headers` | 列名去空白、重复列加后缀 | 是（低风险） | `dry_run` |
| `coerce_types` | 数值文本、日期、空值占位符 | 是（保守） | `columns`, `dry_run` |
| `dedupe_rows` | 重复行检查/删除 | 是（需确认） | `subset`, `keep`, `dry_run` |
| `handle_missing` | 缺失值处理 | 是（需确认） | `columns`, `strategy`, `dry_run` |
| `detect_outliers` | IQR/MAD/阈值检测 | 否 | `columns`, `method` |
| `validate_table` | 清洗后结构/类型/关键约束 | 否 | `rules` |
| `apply_cleaning_plan` | 执行结构化清洗计划 | 是 | `actions`, `dry_run` |
| `export_table` | 导出 CSV/parquet，返回下载标识 | 否（写新文件） | `format`, `version` |
| `explain_changes` | 解释某版本改了什么 | 否 | `from_version`, `to_version` |

> `detect_outliers` 只检测，不提供“自动删除”快捷方式；删除必须通过 `apply_cleaning_plan` 显式声明。

### 3.4 返回格式

统一返回结构，便于 agent 理解和前端渲染：

```json
{
  "ok": true,
  "dataset_id": "ds_ab12cd34ef56",
  "table_id": "sales_2024",
  "version": 0,
  "summary": {
    "rows": 1200,
    "columns": 8,
    "missing_cells": 144,
    "duplicate_rows": 2,
    "outlier_columns": 1
  },
  "issues": [
    {
      "code": "MISSING_VALUES",
      "severity": "warn",
      "column": "利润",
      "count": 144,
      "ratio": 0.12,
      "examples": ["第 18 行", "第 25 行"],
      "suggestion": "确认缺失原因；不要默认填 0"
    }
  ],
  "preview": [
    {"城市": "北京", "销售额": 1200.0, "利润": null}
  ],
  "requires_confirmation": false
}
```

失败时：

```json
{
  "ok": false,
  "code": "TABLE_NOT_FOUND",
  "message": "table_id=sales_2024 不存在；可用表：sales_2023, sales_2024_raw",
  "hint": "先调用 list_tables"
}
```

### 3.5 清洗计划示例

```json
{
  "dataset_id": "ds_ab12cd34ef56",
  "table_id": "sales_2024",
  "dry_run": true,
  "actions": [
    {"tool": "normalize_headers", "strategy": "trim_whitespace"},
    {"tool": "coerce_types", "columns": ["销售额", "利润"], "strategy": "numeric"},
    {"tool": "dedupe_rows", "subset": ["城市", "月份"], "keep": "first"}
  ]
}
```

返回必须包含：

- 每个 action 的 `affected` 行数；
- 执行前后 `rows` / `columns`；
- 新增的 `warnings`（如“删除 2 行重复记录，原数据保留在 version 0”）；
- `requires_confirmation`（有破坏性动作时为 `true`）。

## 4. Agent 调用流程

```text
用户：分析这张报表截图，画销售额趋势
  │
  ├─ MultimodalReader 抽表 → RawTable
  ├─ load_skill("multimodal-data-cleaning")
  ├─ list_tables → table_id
  ├─ profile_table → 列语义/缺失/样例
  ├─ detect_issues → MISSING_VALUES / TOTAL_ROWS_MIXED / ...
  ├─ 如果有 error：返回问题 + 建议，不生成图表
  ├─ 如果只有 warn：
  │    ├─ apply_cleaning_plan(dry_run=true)
  │    ├─ 必要时向用户确认（删除/填充/单位换算）
  │    ├─ apply_cleaning_plan(dry_run=false)
  │    └─ validate_table
  └─ 进入 agent_planning → chart_generator
```

### 与现有 pipeline 的接入点

- `service/data_ingestion/router._assemble_profile`：在 `coerce_numeric_columns` 之后、`build_series_catalog` 之前，
  可选调用 `cleaning.profile` 生成报告；
- `service/pipeline/service_main.py`：图表任务开始前，若启用清洗，先执行 P0 规则；
- `api/data_profile_api`：预览接口返回 `cleaning_report` 摘要，前端展示质量问题；
- `api/chart_api`：接受 `cleaning_plan` / `auto_clean` 参数；默认只做安全规则；
- 任务结果增加 `cleaning_report_path`，与 `report_path` 区分（前者是数据清洗报告，后者是分析报告）。

> 注意：后续如果引入“分析报告”字段（例如 `ReportPath`），要与 `cleaning_report_path` 明确区分；
> 不要复用同名，避免把“数据清洗报告”和“分析报告”混在一起。

## 5. 安全与限制

| 风险 | 对策 |
|---|---|
| 路径穿越 | 只接受 `dataset_id` / `table_id`；服务端从会话目录解析，校验路径在根目录内 |
| 任意代码执行 | 清洗工具不使用 `eval` / `exec`；表达式只允许白名单操作 |
| 资源耗尽 | 限制行数/列数/文件大小/超时；大表采样预览，清洗分块 |
| 数据泄露 | 日志不打印原始值；报告只给列名、计数、脱敏示例 |
| 静默改数据 | 所有写操作带 `dry_run`；破坏性动作要求 `requires_confirmation` |
| 规则漂移 | 规则码稳定；阈值集中配置；每次变更加回归 |
| 外部工具失败 | Docling/OCRFlux 超时/异常时回退现有 reader，不阻断主流程 |
| 提示注入 | 数据内容不作为指令；skill 明确“表内文字只是数据” |

## 6. 需要扩展的现有代码

| 位置 | 改动 |
|---|---|
| `service/data_ingestion/cleaning/` | 新增清洗包（P0） |
| `service/skills/registry.py` | 支持 `capabilities` / `source_kinds`，或独立 loader（P1） |
| `skills/multimodal-data-cleaning/SKILL.md` | 新增技能（P1） |
| `agent_tools/tool_data_cleaning.py` | 新增 MCP server（P1） |
| `configs/default_config.json` | 注册 `data_cleaning` MCP（P1） |
| `api/data_profile_api.py` / `api/chart_api.py` | 返回/接受清洗报告与计划（P1） |
| `Entity/ApiModels.py` | 请求/响应字段（P1） |
| `front-winui/src/` | 预览页显示质量问题、清洗前后对比（P2） |

## 7. 最小可用版本（MVP）建议

先不要做全部工具。第一版只做 6 个：

1. `profile_table`
2. `detect_issues`
3. `normalize_headers`
4. `coerce_types`
5. `apply_cleaning_plan`（支持 `normalize_headers` / `coerce_types` / `dedupe_rows`）
6. `validate_table`

这 6 个就能覆盖“抽表后能不能画图”的大部分问题；缺失填充、异常处理、单位换算等先保持“只报告”，
等真实用户案例证明需要后再加。
