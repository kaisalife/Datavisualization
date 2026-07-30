# AGENTS.md - 数据可视化服务项目规范

本文件是项目级记忆，会被注入到 LLM 的 system prompt，生成图表计划与代码时请遵循以下规范。

## 项目概述

DataVisualServer 是一个基于 LangChain + pyecharts 的数据可视化服务。用户上传数据文件（Excel/CSV），通过 LLM agent 自动分析数据特征、生成图表计划、逐个生成并调试 pyecharts 可视化图表，输出 HTML 文件。

## 图表生成规范

- **图表库**：使用 `pyecharts`，禁止使用 matplotlib / seaborn / plotly
- **图表类型**：优先使用 Line / Bar / Scatter / Pie / HeatMap / Grid（多图组合）
- **输出格式**：每个图表渲染为独立 HTML 文件，用 `.render()` 方法保存
- **中文支持**：图表标题、轴标签必须支持中文，全局配置 `InitOpts(width="900px", height="500px")`
- **配色**：使用 pyecharts 内置主题（如 ThemeType.LIGHT），避免默认刺眼配色

## 命名约定

- **图表文件**：`charts/<数据文件名>/chart_<时间戳>_<序号>.html`，例如 `charts/季度数据/chart_20260709_1.html`
- **计划文件**：`charts/<数据文件名>/all_plans.json`
- **Python 变量**：snake_case（如 `data_preview`、`chart_path`）
- **类名**：PascalCase（如 `GenerateChartWithPromptRequest`）

## 代码风格

- Python 3.10+，4 空格缩进，禁止 tab
- 字符串优先双引号 `"`
- 函数/类文档字符串用中文，说明用途、参数、返回值
- import 顺序：标准库 -> 第三方 -> 本项目，各组间空行
- 路径处理用 `pathlib.Path`，禁止字符串拼接路径

## 目录结构

```
DataVisualServer/
├── agent/            # LLM agent 封装（BaseAgent）
├── agent_tools/      # MCP 工具（run_code 沙箱）
├── Entity/           # Pydantic 请求/响应模型
├── prompts/          # LangChain prompt 模板
├── RAG/              # 图表知识库检索（Chroma + Qwen embedding）
├── service/          # 业务管线（service_main / chart_generator / memory）
├── configs/          # 默认配置 JSON
└── app.py            # Flask HTTP 端点
```

## 数据处理规范

- 数据预览前先用 `get_smart_file_preview` 智能截断，避免超长输入
- 生成图表代码前，先从数据接口信息推断字段类型
- RAG 检索图表设计知识库，优先复用已有图表模板

## 错误处理

- 图表生成失败时进入 debug 循环（最多 3 次重试），用 `get_agent_debug_chart_prompt` 分析错误
- 不要静默吞掉异常，错误信息要回传到 `failed_plans`
