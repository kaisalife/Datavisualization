from langchain_core.prompts import ChatPromptTemplate

# ============================================================
# 1. 图表规划（plan 阶段：拆分每个图表为独立 plan）
# ============================================================

agent_chart_designer_prompt = """
你是数据可视化规划专家。基于数据语义特征，为每个图表生成一个 plan（含类型/字段映射/布局），供生成阶段逐个执行。

## 输入
- canonical_dataset（权威）：列 name/dtype/semantic_role(time/measure/dimension/id)、stats、preview_rows、semantic_hints.detected_patterns
- data_file_path、data_preview：辅助
- user_chart_config：用户图表配置偏好（可选）
- 用户需求

## 规划原则
1. 从 canonical_dataset.schema 读列名和 semantic_role
2. semantic_role="time" -> 首选 x_axis；"measure" -> 首选 y_axis/value；"dimension" -> 分组/category
3. detected_patterns 含 time_series -> 优先 Line/Area；含 categorical_comparison -> 优先 Bar/Pie
4. 根据用户需求规划 2-4 个图表，每个一个 plan

## 数据访问（DuckDB 为主）
数据已注册为 DuckDB 表，生成阶段通过 `conn.sql("SELECT ... FROM {{table_name}}")` 查询。
plan 的数据字段填**真实列名**（从 canonical_dataset.schema），data_interface.available = false。

## 布局规划（避免标题/图例重叠）
每个 plan 含 layout 字段：
- series ≤ 4：legend_pos="top", grid_top="12%", grid_bottom="8%"
- series > 4 或名称长：legend_pos="bottom", grid_top="8%", grid_bottom="12%"
- Pie：legend_pos="top" 或 "right"

## 输出格式（严格 JSON，仅返回 JSON）
```json
{{
  "plans": [{{
    "plan_id": "1",
    "plan_name": "图表名称",
    "chart_type": "Bar",
    "chart_title": "标题",
    "chart_reason": "选择此类型的原因",
    "x_axis": "列名",
    "y_axis": ["列名1", "列名2"],
    "use_column_names": true,
    "data_interface": {{"available": false}},
    "execution_order": 1,
    "layout": {{
      "legend_pos": "bottom",
      "grid_top": "8%",
      "grid_bottom": "12%"
    }}
  }}]
}}
```

## chart_type 可选值
Line, Bar, Scatter, Pie, Area, Histogram, Boxplot, Heatmap, Candlestick, Radar, Funnel, Gauge, Treemap, WordCloud, Graph, Parallel, Sankey, ThemeRiver

## 必填字段
plan_id, plan_name, chart_type, chart_title, chart_reason, x_axis, y_axis, use_column_names, data_interface, execution_order, layout
"""

# ============================================================
# 2. 图表生成（每个 plan 单独执行）
# ============================================================

agent_generate_chart_prompt = """
按计划生成单个图表的 pyecharts 代码。

## 数据获取（DuckDB）
数据已注册到 DuckDB，全局变量 `conn` 已由框架注入，直接查询：
```python
df = conn.sql("SELECT * FROM {{table_name}}").df()
df = conn.sql("SELECT category, SUM(amount) as total FROM {{table_name}} GROUP BY category ORDER BY total DESC").df()
```
- conn 是全局变量，不需要 import duckdb
- 表名/列名区分大小写，用双引号包裹: `SELECT "ColumnName" FROM "{{table_name}}"`
- 结果用 .df() 转 DataFrame

## 按计划创建图表
- 图表类型：严格用 plan_details.chart_type
- 标题：严格用 plan_details.chart_title
- 数据列：严格用 plan_details.x_axis / y_axis 的列名（如 df["销售额"].tolist()）
- 不得使用计划外的数据列

## 参考文档
参考 {{reference_docs}} 中的 pyecharts 示例，复用其导入/结构/API。

## 保存图表
- 只调 `chart.render()`，不传 path、不拼目录、不 os.makedirs（框架自动注入路径）

## 用户配置（user_config）
- width/height -> InitOpts(width=..., height=...)
- theme -> InitOpts(theme=ThemeType.DARK)
- color/palette -> set_series_opts/itemstyle
- 默认：InitOpts(width="900px", height="500px") + ThemeType.LIGHT

## 布局（防标题/图例重叠，必须遵守）
- 标题：TitleOpts(pos_top="2%", pos_left="center")
- 图例（plan_details.layout.legend_pos）：
  - "top"/series≤4：LegendOpts(pos_top="2%", pos_right="3%", orient="horizontal")
  - "bottom"/series>4：LegendOpts(pos_bottom="2%", pos_left="center", orient="horizontal")
- Grid：GridOpts(pos_top=layout.grid_top 或 "12%", pos_bottom=layout.grid_bottom 或 "8%", pos_left="8%", pos_right="5%")
- Pie：center=["50%","55%"], radius=["30%","60%"]
- 多 series：set_series_opts(label_opts=LabelOpts(is_show=False))

## 输出
仅返回 Python 代码，完整可执行，含所有 import。
"""

# ============================================================
# 3. 代码调试（生成失败时修复）
# ============================================================

agent_debug_chart_prompt = """
修复图表生成代码。

输入：plan_details / failed_code / error_message / dataset_summary / table_name / user_config

1. 分析错误（traceback 最后一行异常类型 + 行号）
2. 修复代码，保持计划要求（chart_type/chart_title/数据列）
3. 只调 chart.render()（不传 path，框架自动注入）
4. 遵守布局规范（标题/图例防重叠，与生成阶段一致）
5. 仅返回 Python 代码

常见错误：
- KeyError: 列名与 dataset_summary 不匹配，用原始列名
- TypeError/ValueError: NaN 未清洗，加 df.fillna(0) 或 pd.to_numeric(errors='coerce')
- pyecharts add_yaxis: 至少传 (series_name, y_data)
"""

# ============================================================
# 4. 数据预览（file 源，legacy 流水线用）
# ============================================================

agent_data_preview_prompt = """
你是一位精通数据文件处理的专家，能够智能读取各种格式的数据文件。

Pandas 参考知识：
{{pandas_reference}}

输入信息：
- 数据文件路径：{data_file_path}
- 当前步骤：{current_step}

工作流程分为两步：

**第一步：获取简单数据预览**
当 current_step = "preview" 时：
1. 智能读取数据文件（支持 .csv、.xlsx、.xls、.parquet 等常见格式）
   - CSV 编码尝试顺序：utf-8, gbk, gb2312, gb18030, latin1
   - 同时尝试不同的分隔符：sep=',', sep='\t', sep=';'
2. 数据清洗：处理 NaN、类型转换（pd.to_numeric errors='coerce'）
3. 生成数据预览（形状、列名、前10行），用 print() 输出

**第二步：构建数据接口**
当 current_step = "interface" 时：
1. 基于预览理解数据结构
2. 生成数据接口模块（get_all_columns/get_column_data/get_x_y_data/get_multi_series_data 等）
3. 先 print("---DATA_INTERFACE_CODE---") 再输出代码

仅返回代码，不要其他说明。
"""

# ============================================================
# Prompt 工厂函数
# ============================================================

def get_agent_chart_designer_prompt() -> ChatPromptTemplate:
    return ChatPromptTemplate([
        ("system", agent_chart_designer_prompt),
        ("human", "{data_file_path}\n数据预览:{data_preview}\n数据接口信息:{data_interface_info}\ncanonical_dataset(权威):\n{canonical_dataset}\n用户自定义图表配置:{user_chart_config}\n{user_prompt}\n{mcp_prompt}\n{skill_prompt}")
    ]).partial(canonical_dataset="(未提供)", user_chart_config="(未提供)")


def get_agent_generate_chart_prompt() -> ChatPromptTemplate:
    return ChatPromptTemplate([
        ("system", agent_generate_chart_prompt),
        ("human", "数据文件: {data_file_path}\n数据预览: {data_preview}\n数据列 schema:\n{dataset_summary}\nDuckDB表名: {table_name}\n计划: {plan_details}\n参考文档: {reference_docs}\n用户自定义图表配置: {user_config}")
    ]).partial(dataset_summary="(未提供)", table_name="", user_config="(未提供)")


def get_agent_data_preview_prompt(pandas_reference: str = "") -> ChatPromptTemplate:
    return ChatPromptTemplate([
        ("system", agent_data_preview_prompt),
        ("human", "数据文件路径: {data_file_path}\n当前步骤: {current_step}\n数据预览: {data_preview}")
    ]).partial(pandas_reference=pandas_reference)


def get_agent_debug_chart_prompt() -> ChatPromptTemplate:
    return ChatPromptTemplate([
        ("system", agent_debug_chart_prompt),
        ("human", "计划: {plan_details}\n失败代码:\n{failed_code}\n错误:\n{error_message}\n数据预览:\n{data_preview}\n数据列 schema:\n{dataset_summary}\nDuckDB表名: {table_name}\n用户自定义图表配置: {user_config}")
    ]).partial(dataset_summary="(未提供)", table_name="", user_config="(未提供)")


# ============================================================
# 5. 数据库查询（db 源）
# ============================================================

agent_db_query_prompt = """
你是一位精通 SQL 的数据工程师。用户给你数据库 schema 和可视化需求，你需要生成一条只读的 SELECT 语句。

**硬性约束**：
1. 仅允许 SELECT / SHOW / DESC / EXPLAIN / WITH 开头，禁止写入或 DDL。
2. 只用 schema 中出现的表和列，不要虚构。
3. 对结果集大小控制：主动 GROUP BY 或 LIMIT。
4. 优先聚合到"可视化友好"的量级（100~10000 行）。

**输出格式**（严格 JSON）：
```json
{{
  "sql": "SELECT ...",
  "explanation": "一句话解释",
  "expected_columns": ["col1", "col2"]
}}
```
"""

def get_agent_db_query_prompt() -> ChatPromptTemplate:
    return ChatPromptTemplate([
        ("system", agent_db_query_prompt),
        ("human", "数据库 schema:\n{db_schema}\n\n用户需求:\n{user_prompt}\n\n用户提示的表(可选):\n{hint_table}"),
    ])


agent_db_multi_query_prompt = """
你是一位精通 SQL 和数据可视化的数据工程师。生成多条独立的 SELECT 语句，每条支撑一个可视化视角。

**硬性约束**：
1. 仅允许 SELECT，禁止写入或 DDL。
2. 只用 schema 中的表和列。
3. 每条 SQL 结果集 100~10000 行，主动 GROUP BY / LIMIT。
4. 每个查询聚焦独立视角（时间趋势/维度分组/top-N/占比）。
5. 生成 {min_queries}~{max_queries} 条 query。

**输出格式**（严格 JSON）：
```json
{{
  "queries": [
    {{"sql": "SELECT ...", "name": "query_name", "explanation": "...", "expected_columns": ["col"]}}
  ]
}}
```
"""

def get_agent_db_multi_query_prompt() -> ChatPromptTemplate:
    return ChatPromptTemplate([
        ("system", agent_db_multi_query_prompt),
        ("human", "数据库 schema:\n{db_schema}\n\n用户需求:\n{user_prompt}\n\n最多生成 {max_queries} 条 query。"),
    ]).partial(min_queries="2", max_queries="5")


# ============================================================
# 6. 代码补全（scientific 模式）
# ============================================================

agent_viz_code_completion_prompt = """
你是科学 Python 代码助手。用户提供一段 Python 代码 + 可视化需求。

**任务**：
1. 推测原代码的"结果变量"（最终输出的数据变量名，如 DataFrame/数组）
2. 生成 mock 数据代码（简单模拟结果变量，3-5 行 DataFrame，符合推测的列名/类型/语义）
3. 生成可视化片段（用结果变量，追加到原代码末尾，不修改原代码），优先用与用户风格一致的库

**限制**：不引入 numpy/matplotlib/plotly/seaborn/pandas/scipy/pyecharts 外的库；不做网络/文件访问；mock 数据要简单。

**输出严格 JSON**：
```json
{{
  "result_var": "result_df",
  "mock_data": "import pandas as pd\\nresult_df = pd.DataFrame({{'category':['A','B','C'],'value':[10,20,30]}})",
  "snippet": "from pyecharts.charts import Bar\\nchart = Bar().add_xaxis(result_df['category'].tolist()).add_yaxis('值', result_df['value'].tolist())\\nchart.render('chart.html')",
  "explanation": "说明",
  "libs": ["pyecharts"]
}}
```

注意：snippet 中的变量名必须与 result_var 一致；mock_data 必须定义该变量；系统会用 mock_data 测试 snippet，测试通过才会追加到原代码。
"""

def get_agent_viz_code_completion_prompt() -> ChatPromptTemplate:
    return ChatPromptTemplate([
        ("system", agent_viz_code_completion_prompt),
        ("human", "用户代码摘要:\n{source_summary}\n\n用户完整代码:\n```python\n{full_source}\n```\n\n可视化需求:\n{user_prompt}\n\n偏好库(可选): {scientific_lib}"),
    ])
