# 数据清洗工具集（调研与落地记录）

> 目标：在图表生成之前，把真实用户数据（CSV / Excel / JSON / 数据库 / API / 图片 / PDF / Office 内嵌表格）
> 清洗成**可追溯、可验证、可复现**的表格与 series，而不是让模型直接面对脏数据自由发挥。

## 调研结论

截至 **2026-10-22**，没有检索到一个成熟的、专注“多模态数据清洗”的现成 skill / MCP 一体化工具集。
现有生态基本分成三类，彼此不覆盖：

| 类别 | 代表 | 能解决 | 缺口 |
|---|---|---|---|
| 文档 / OCR 抽表 | Docling、OCRFlux、mcp-ocr、Unstructured | 图片、PDF、扫描件、Office 内嵌表格 → 文本或表格 | 不做表头/数值/缺失/重复/单位清洗，也不做质量报告 |
| 表格清洗 MCP | `AstyanM/mcp-data-science`、MCP Pandas、Data Exploration | CSV / Excel / Parquet 的通用 pandas 清洗 | 不处理图片/PDF，缺少多模态抽表、表头合并、跨页续表、来源追溯 |
| Agent Skills | Anthropic `xlsx` / `pdf` / `docx`、通用 `data-cleaning` / `data-transform` | 文件操作、pandas/numpy 变换 | 规则偏通用，不是面向“抽表后的中文报表”清洗，缺少确定性校验和审计 |

因此本项目不直接引入某个“万能工具”，而是采用**组合方案**：

```text
现有 reader 抽表
  → 确定性结构清洗（表头/标题行/合并单元格/编码）
  → 确定性值清洗（数值文本/空值占位符/类型）
  → 数据质量检查（缺失/重复/异常/单位/时间连续性）
  → 语义 series 拆分
  → 图表规划与生成
```

其中：

- **P0（默认、无新增重依赖）**：复用现有 `service/data_ingestion/`，补一个确定性清洗模块和质量报告；
- **P1**：把清洗能力包装成 MCP 工具 + `multimodal-data-cleaning` skill，供 agent 按需调用；
- **P2（按需）**：在 OCR/版面解析失败时，接入 Docling / OCRFlux 等外部抽取器，只作为 reader 适配层，不让它们承担清洗职责。

## 三条硬约束

1. **原始数据只读**：上传文件、原始表、抽表结果都不覆盖；清洗结果写入新版本，并记录来源与哈希。
2. **默认只报告，不静默修改**：表头空白、重复列名、数值文本、编码这类可逆且低风险的规则可以自动执行；
   缺失填充、删除重复行、剔除异常值、单位换算、合并不同表等有业务含义的操作必须显式确认。
3. **确定性与可复现优先**：数字、行数、列数、缺失率由代码计算；LLM 只用于解释、建议和歧义提问，
   不能生成或补造数据值。

## 目录

| 文件 | 内容 |
|---|---|
| [01-调研结论.md](01-调研结论.md) | 本地与外部工具调研、候选对比、为什么没有直接采用 |
| [02-工具清单.md](02-工具清单.md) | 现有内部能力、可接入的外部工具、依赖策略 |
| [03-清洗流程与规则.md](03-清洗流程与规则.md) | 清洗流水线、规则目录、质量维度、清洗报告格式 |
| [04-MCP与Skill设计.md](04-MCP与Skill设计.md) | MCP 工具契约、skill 结构、agent 调用流程、安全边界 |
| [05-验收与落地计划.md](05-验收与落地计划.md) | P0/P1/P2 交付物、测试矩阵、验收标准、风险 |

## 与现有代码的关系

当前项目**已经有相当一部分清洗能力**，只是分散在接入链路里，没有统一的“清洗工具集”概念：

- `service/data_ingestion/router.py`：列名清洗、数值归一化入口、原始表保存；
- `service/data_ingestion/normalize.py`：`1,200` / `12.5%` / `(1,200)` / 全角数字 / 空值占位符；
- `service/data_ingestion/readers/excel_reader.py`：合并表头、标题行、空白 sheet、数据区纵向合并；
- `service/data_ingestion/readers/file_reader.py`：CSV 编码、分隔符、JSON/JSONL；
- `service/data_ingestion/readers/multimodal_reader.py`：图片/PDF 抽表、跨页续表、一图多表；
- `service/data_ingestion/readers/office_image_reader.py`：docx/pptx/xlsx 内嵌表格截图；
- `service/data_ingestion/profiler.py`：schema、统计、时间/指标/维度/ID 语义；
- `service/data_ingestion/series/splitter.py`：长表透视、自然时间排序、重复时间点聚合。

缺的是：**统一的质量检查、显式的清洗计划、可审计的清洗报告、以及给 agent 的稳定工具接口**。
本目录先记录设计与边界，后续代码落地时按 [05-验收与落地计划.md](05-验收与落地计划.md) 推进。
