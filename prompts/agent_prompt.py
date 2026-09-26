from langchain_core.prompts import ChatPromptTemplate

# ============================================================
# 1. 图表规划 prompt 已拆至 chart_designer_prompt.py（v3.1 read_recipe 选用）
# ============================================================
from prompts.chart_designer_prompt import chart_designer_prompt as agent_chart_designer_prompt  # noqa: F401
from prompts.chart_designer_prompt import get_agent_chart_designer_prompt  # noqa: F401
from prompts.chart_gen_prompt import (  # noqa: F401
    agent_debug_chart_prompt, agent_generate_chart_prompt,
    get_agent_debug_chart_prompt, get_agent_generate_chart_prompt,
)


# ============================================================
# 2. 图表生成（每个 plan 单独执行）
# ============================================================


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


def get_agent_data_preview_prompt(pandas_reference: str = "") -> ChatPromptTemplate:
    """数据预览 prompt 工厂（legacy 流水线用）。"""
    return ChatPromptTemplate([
        ("system", agent_data_preview_prompt),
        ("human", "数据文件路径: {data_file_path}\n当前步骤: {current_step}\n数据预览: {data_preview}")
    ]).partial(pandas_reference=pandas_reference)


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
