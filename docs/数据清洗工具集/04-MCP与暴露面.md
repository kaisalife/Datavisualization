# MCP 与暴露面设计

## 1. 定位

view 层的核心是**库函数**（`service/data_view/`），API、图表编排、测试直接调用；
MCP 只是给 agent 的薄适配器，不保存状态、不实现业务逻辑。

旧方案有 9 个工具（评估/建议/预览/应用/确认……），本质是把多阶段流程搬进协议层，已废弃。
新方案只要两个工具——因为 view 是确定性的、可逆的、不需要 dry-run/confirm 双态：

| 工具 | 参数 | 返回 | 副作用 |
|---|---|---|---|
| `describe_dataset` | `dataset_id` | dataset 的表清单、列名/dtype、行数、样品前 3 行、已有 view 列表（含 spec 摘要） | 无 |
| `run_view` | `dataset_id`、`spec`、`mode=preview\|materialize` | `view_id` + 输出 schema + 前 5 行样品；`materialize` 才落盘 | 仅 materialize 写 parquet |

`preview` 只在内存执行并返回样品，不写文件——agent 想"先看看再决定"用 preview，
确定要复用（出图）用 materialize。两者跑的是同一份 spec，不存在行为分叉。

## 2. 状态模型

跟现有 `agent_tools` 一致：不传 DataFrame、不传路径，只传句柄。

```text
dataset_id (ds_<12hex>)  → 会话目录，独立于 MCP 进程生命周期
view_id (vw_<hash12>)    → runtime/datasets/<ds>/views/<view_id>.parquet
```

- MCP 进程重启不影响任何状态（都在磁盘/主服务内存里）；
- `run_view` 校验 `dataset_id` 格式与 view 输出路径必须落在该会话目录内，防路径穿越；
- 返回给 LLM 的只有 schema、行数、样品和 id；文件路径、引擎连接、原始数据不出现在上下文里。

## 3. 参数与返回示例

`describe_dataset(ds_ab12cd34ef56)`：

```json
{
  "tables": [
    {"name": "table_0", "rows": 240, "columns": [
        {"name": "月份", "dtype": "str", "role": "time"},
        {"name": "城市", "dtype": "str", "role": "dimension"},
        {"name": "销售额", "dtype": "float", "role": "measure"}]}
  ],
  "views": [
    {"view_id": "vw_9f2c...", "spec_summary": "sql: select 月份... group by 月份", "rows": 12}
  ]
}
```

`run_view`（SQL 例：重复类别聚合 + Top-N，这是最常见的一类派生需求）：

```json
// 请求
{"dataset_id": "ds_ab12cd34ef56",
 "spec": {"kind": "sql",
          "inputs": ["table_0"],
          "sql": "select 城市, sum(销售额) as 销售额 from d1
                  group by 城市 order by 销售额 desc limit 10",
          "params": {}},
 "mode": "materialize"}

// 返回
{"view_id": "vw_7a11...", "rows": 10,
 "schema": [{"name": "城市", "dtype": "str"}, {"name": "销售额", "dtype": "float"}],
 "sample": [{"城市": "上海", "销售额": 15230.0}]}
```

失败返回：

```json
{"ok": false, "code": "WRITE_STATEMENT_REJECTED",
 "message": "SQL 含写操作语句（delete），已拒绝；只允许单条 SELECT/WITH",
 "hint": "请提交只读查询"}
```

错误码固定枚举：`SPEC_INVALID` / `WRITE_STATEMENT_REJECTED` / `PLUGIN_NOT_FOUND` /
`SCHEMA_MISMATCH` / `EMPTY_RESULT`（输出 0 行且未声明允许为空）。

## 4. 接入点

| 位置 | 改动 |
|---|---|
| `service/data_view/` | 新增核心库（见 03 §3） |
| `agent_tools/tool_data_view.py` | 新增 MCP 工具壳（fastmcp，stdio，参照 `run_code` 注册进 `configs/default_config.json`） |
| `service/data_ingestion/series/splitter.py` | series manifest 记录来源（identity 默认 / view 派生） |
| `api/data_profile_api.py` | 预览响应带 `views` 列表，供前端核对 |
| plan / prompts | **不改** |

agent 的使用方式是自然形成的：规划 agent 读 series 索引时，如果索引里没有合适视角
（如"按月合计"不存在），它先 `run_view` 造一条再规划——这不是新增阶段，
而是规划阶段的一次普通工具调用，跟现在调用 `get_series` 同级。

## 5. skill

特殊场景的领域知识仍然走 skill（`skills/`），不写进工具：

- 说明"什么场景值得造派生 view"（K 线、高频时序、多模态抽表后清洗）；
- 给出典型 SQL/插件组合模板；
- 提醒边界：负值饼图这类问题不是靠改数据解决的，是换图型——view 层不为图表达标服务。

skill 只影响 agent 选择 spec 的方式，不影响执行器行为；新增场景 = 新增/修改 skill 文本。

## 6. 安全边界

| 风险 | 对策 |
|---|---|
| 写操作/多语句 SQL | 复用 `ensure_read_only`（剥字符串与注释后校验，`WHERE note='a;b'` 不误判） |
| 路径穿越 | 只收 `dataset_id`；view 路径由服务端拼装并校验在会话目录内 |
| 任意代码执行 | 插件只能引用注册表里的 `name+version`；不接受函数体；注册表启动时静态扫描 |
| 资源耗尽 | SQL 执行限时；输出行数超阈值（默认 200 万行）直接拒绝并提示加 LIMIT |
| 数据泄露 | 响应只含 schema/样品/计数；日志不打敏感值 |
| LLM 造错误 spec | 校验失败回传结构化错误让 agent 修正一次；二次失败即任务失败，绝不带病执行 |

## 7. 明确不做的

- 不做 `get_or_create` 之外的第九个 convenience 工具；两个工具 + 现有 series 索引已覆盖全部读写流；
- 不让 MCP 直接读文件/数据库——数据永远先经接入层成为 dataset；
- 不在本章定义图表建议逻辑——`run_view` 不返回任何"该画什么图"的内容。
