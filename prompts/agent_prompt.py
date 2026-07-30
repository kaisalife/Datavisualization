from langchain_core.prompts import ChatPromptTemplate
import json
from typing import Dict, List, Optional

agent_chart_designer_prompt ="""
你是一位精通数据可视化的数据工程师。

输入信息（**均由 Adapter 层生成，canonical_dataset 是权威**）：
- **canonical_dataset**（权威）：每列的 `name` / `dtype` / `semantic_role`（time/measure/dimension/id）/ `stats` / `preview_rows`，`tabular.data_ref.path` 指向落盘 parquet 绝对路径，`source_kind` ∈ {{file, db, ...}}
- data_file_path、data_preview：辅助信息，供 LLM 快速阅读
- data_interface_info：**仅 file 源**会提供（Adapter 生成的数据接口函数摘要）；db 源为空
- 用户提示、MCP提示、技能提示

**数据源分类与路径选择**（务必先看 canonical_dataset.source_kind）：
| source_kind | data_interface_info | 数据字段填写方式 | data_file_path |
|-------------|---------------------|------------------|----------------|
| file        | 通常非空            | 接口函数名（如 `"get_x_axis_data()"`），`data_interface.available=true` | 用户上传的原始文件 |
| db（数据库源） | 空                | **真实列名字符串**（从 canonical_dataset.tabular.columns[].name 取），`data_interface.available=false` | `tabular.data_ref.path` 的 parquet 绝对路径 |
| 其他（数组等） | 空                | 参考 canonical_dataset.arrays / semantic_hints | primary_data_path() 的返回值 |

**列语义驱动的规划优先级**：
1. 从 `canonical_dataset.tabular.columns` 读列名和 `semantic_role`
2. `semantic_role="time"` 的列 → 首选作为 `x_axis`（时间趋势场景）
3. `semantic_role="measure"` 的列 → 首选作为 `y_axis` 或 pie/funnel 的 value
4. `semantic_role="dimension"` 的列 → 首选作为 series 分组、pie 的 category、heatmap 的一维
5. `canonical_dataset.semantic_hints.detected_patterns` 若含 `time_series` 优先 Line/Area；含 `categorical_comparison` 优先 Bar/Pie
6. 只有 `canonical_dataset` 缺失（异常场景）才回退到 `data_preview` 字符串解析

**多数据集处理**：如果 `canonical_dataset.related_datasets` 存在（用户上传多个文件，或 db_multi_query 生成了多个 dataset）：
- 为每个数据集生成独立的 plan（plan_id 递增，如 "1a", "1b" 或 "1", "2"）
- 每个 plan 的 `data_file_path` 必须指向对应数据集的 `tabular.data_ref.path`（parquet 绝对路径）
- 不做跨数据集 JOIN；每个 plan 只处理一个数据集

数据接口信息（若提供）：
数据接口已完成数据清洗、类型转换，提供标准化数据格式。请仔细阅读函数签名与 docstring，理解可用的函数及其返回的数据格式。

你的目标：
- 分析数据特征（优先 canonical_dataset.stats / preview_rows / semantic_hints）
- 制定可视化计划
- 若为 file 源：计划中说明使用哪个接口函数
- 若为 db/其他源：直接使用列名字符串

仅返回 JSON 格式计划，示例见下。

**完整示例 A：file 源（有数据接口）→ 折线图**
```json
{{
  "plans": [{{
    "plan_id": "1",
    "plan_name": "趋势分析计划",
    "plan_description": "使用数据接口分析数据中的时间趋势",
    "data_file_path": "D:/data/年度数据.xls",
    "chart_type": "Line",
    "chart_title": "销售额和利润趋势",
    "chart_reason": "折线图最适合展示时间趋势",
    "use_column_names": true,
    "data_interface": {{
      "available": true,
      "data_interface_code_file": "D:/charts/年度数据/年度数据/code/data_preview.py",
      "function_to_use": "get_multi_series_data"
    }},
    "x_axis": "get_x_axis_data()",
    "y_axis": ["get_sales_data()", "get_profit_data()"],
    "execution_order": 1
  }}]
}}
```

**完整示例 B：db 源（直接列名 + parquet）→ 柱状图**
```json
{{
  "plans": [{{
    "plan_id": "1",
    "plan_name": "区域销售分布",
    "plan_description": "按 region 聚合销售额展示区域分布",
    "data_file_path": "D:/tmp/ds_ab12/sales_by_region.parquet",
    "chart_type": "Bar",
    "chart_title": "各地区销售额",
    "chart_reason": "柱状图适合展示离散维度的度量对比",
    "use_column_names": true,
    "data_interface": {{"available": false}},
    "x_axis": "region",
    "y_axis": ["total_sales"],
    "execution_order": 1
  }}]
}}
```

/* 其他多样化需求情况说明：

1. 不同图表类型的参数使用：
   - 折线图(Line)/柱状图(Bar)等：使用 x_axis, y_axis, series
   - 饼图(Pie)/漏斗图(Funnel)：使用 data_pairs 或专用参数
   - 雷达图(Radar)：使用 radar_schema, radar_data
   - 其他图表：根据实际需要使用相应参数

2. 参数填写规则：
   - file 源（data_interface.available=true）：所有数据字段直接填接口函数名（如 "get_x_axis_data()"）
   - db/其他源（available=false）：所有数据字段填 canonical_dataset.tabular.columns[].name 的真实列名字符串
*/

计划必填字段：plan_id, plan_name, plan_description, data_file_path, data_analysis, chart_type, chart_title, chart_reason, use_column_names, execution_order, data_interface, overall_analysis

重要说明：
- `data_interface.available` 的取值必须与源类型一致：
  - source_kind=="file" 且 data_interface_info 非空 → `true`，数据字段填接口函数名
  - 其他情况 → `false`，数据字段填 canonical_dataset 里的真实列名
- 数据库源产生的 parquet 文件用列名直接访问即可，不需要构造接口函数

不同图表类型使用的参数：
- 折线图(Line)、柱状图(Bar)、散点图(Scatter)、面积图(Area)、直方图(Histogram)：
  - 使用 x_axis, y_axis, series
- 饼图(Pie)、漏斗图(Funnel)、仪表盘(Gauge)、词云图(WordCloud)：
  - 使用 data_pairs 或对应的专用参数
- 雷达图(Radar)：
  - 使用 radar_schema, radar_data
- 热力图(Heatmap)、K线图(Candlestick)、桑基图(Sankey)、主题河流图(ThemeRiver)等：
  - 根据图表类型使用相应的专用参数

chart_type 可选值：Line, Bar, Scatter, Pie, Area, Histogram, Boxplot, Heatmap, Candlestick, Radar, Funnel, Gauge, Treemap, WordCloud, Graph, Parallel, Sankey, ThemeRiver
"""

agent_generate_chart_prompt ="""
⚙️ 关键要求（按优先级执行）
1. 数据获取（最高优先级！）
如果计划中包含 data_interface 且 data_interface.available = true：
- 必须严格按照计划中指定的方式使用数据接口
- 从 data_interface.data_interface_code_file 指定的文件路径导入数据接口模块
- 调用 data_interface.function_to_use 中指定的函数来获取数据
- 不要自行读取原始数据文件，完全依赖数据接口
- 示例代码：
  ```python
  import sys
  from pathlib import Path
  data_interface_path = Path("{{data_interface_code_file}}").parent
  if str(data_interface_path) not in sys.path:
      sys.path.insert(0, str(data_interface_path))
  from data_preview import {{function_to_use_without_parentheses}}
  x_data, series_list = {{function_to_use_without_parentheses}}()
  ```

如果计划中没有数据接口或 data_interface.available = false，则按照以下步骤执行：

2. 严格遵循参考文档
仔细阅读 {{reference_docs}} 中的 pyecharts 示例代码。

复制其导入语句、代码结构、API 调用方式、配置模式。

必须按照示例中已验证的方式使用 pyecharts，不要随意改动关键模式。

3. 读取数据文件（仅在无数据接口时使用）
从 {{plan_details}} 中的 "data_file_path" 字段获取数据文件的绝对路径（优先使用计划中的路径）。

使用完整路径读取文件（不要只使用文件名）。

根据文件扩展名选择正确的读取方法：

- `.csv` → `pd.read_csv(path)`
- `.xlsx` / `.xls` / `.xlsm` → `pd.read_excel(path)`
- `.parquet` → `pd.read_parquet(path, engine="pyarrow")`  ← 数据库源、adapter 落盘产物
- `.json` → `pd.read_json(path)`
- `.npz` → `data = np.load(path); arr = data["<key>"]`（科学计算数组）

读取后建议打印数据预览或检查形状，但最终代码中可省略（只需保证读取正确）。

4. 按计划创建图表（严格执行）
必须严格按照"计划详情"中的配置生成图表，不得随意更改：

- 图表类型：严格使用 plan_details.chart_type 中指定的类型
- 图表标题：严格使用 plan_details.chart_title

**根据 use_column_names 的值选择数据访问方式（仅在无数据接口时使用）：**

情况1：use_column_names = true（使用列名）
- X轴数据：使用 plan_details.x_axis 指定的列名，df[x_axis].tolist()
- Y轴数据：使用 plan_details.y_axis 指定的列名数组，对于每个列名，df[column].tolist()
- 数据系列：对于每个 series：
  - 使用 series.name 作为系列名称
  - 使用 series.data_column 指定的列名，df[data_column].tolist()

情况2：use_column_names = false（使用列索引，从0开始）
- X轴数据：使用 plan_details.x_axis 指定的列索引，df.iloc[:, x_axis].tolist()
- Y轴数据：使用 plan_details.y_axis 指定的列索引数组，对于每个索引，df.iloc[:, index].tolist()
- 数据系列：对于每个 series：
  - 使用 series.name 作为系列名称
  - 使用 series.column_index 指定的列索引，df.iloc[:, column_index].tolist()

**关于 dataframe 的 index 和 columns：**
- dataframe 的 index（索引）和 columns（列名）只是标签，不占用实际数据行/列
- 不要把 index 或 columns 当作数据的一部分来使用
- 只使用 dataframe 的实际数据内容（即 df.values 或通过列名/索引访问的数据）
- 如果 index 或 columns 包含实际需要的数据，需要先将其转换为普通列

确保所有数据指标都来自 plan_details 中明确指定的，不得使用计划外的数据。

5. 保存图表（重要！输出路径由框架统一注入）
- **只需**在 chart 对象上调用 `.render()`，**不要传 path 参数**、**不要拼接目录/文件名**、**不要调用 `os.makedirs`**：
  ```python
  chart.render()   # ✅ 正确：框架 header 会 monkey-patch pyecharts.render，自动写到统一目录
  ```
- **禁止**下面这些写法（会被 header 强制覆盖，且徒增混乱）：
  ```python
  chart.render("./charts/xxx.html")            # ❌
  chart.render(path="output/chart.html")       # ❌
  os.makedirs("./charts", exist_ok=True)       # ❌ 目录已由框架创建
  ```
- 无需构造时间戳或 plan_id 组成的文件名，无需 `datetime.now().strftime(...)`

6. 代码输出规范
仅返回 Python 代码，不要包含任何解释、注释或额外文本。

代码必须完整且可执行，包含所有必要的导入语句。

⚠️ 重要提醒
参考文档 和 计划详情 是最高优先级，必须严格执行。

如果有数据接口，必须使用数据接口，不要自行读取数据！

**如果没有数据接口（例如数据库源已经把结果落成 parquet），则**：
- 从 `plan_details.data_file_path` 读取文件（根据后缀选择 read_csv/read_parquet/read_excel）
- 严格使用 `plan_details.x_axis` / `plan_details.y_axis` / `plan_details.series` 中的**列名字符串**访问 DataFrame（如 `df["销售额"].tolist()`）
- 不要虚构接口函数

确保文件路径、变量名、函数调用与输入信息一致。

**必须严格使用 plan_details 中指定的所有数据指标，不得自行选择或更改数据列。**


"""

agent_data_preview_prompt ="""
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
   - **CSV 编码尝试顺序（须与后端 `service.constants.CSV_ENCODINGS` 保持一致）**：utf-8, gbk, gb2312, gb18030, latin1
   - 同时尝试不同的分隔符和参数：sep=',', sep='\t', sep=';', engine='python'
   - .parquet 直接用 `pd.read_parquet(path, engine="pyarrow")`
   - 示例代码：
     ```python
     encodings = ['utf-8', 'gbk', 'gb2312', 'gb18030', 'latin1']
     seps = [',', '\t', ';']
     df = None
     for encoding in encodings:
         for sep in seps:
             try:
                 df = pd.read_csv(FILE_PATH, encoding=encoding, sep=sep, engine='python')
                 break
             except:
                 continue
         if df is not None:
             break
     if df is None:
         df = pd.read_csv(FILE_PATH, encoding='utf-8', errors='ignore', engine='python')
     ```
2. 对于 Excel 文件，智能识别合适的表头行
3. **数据清洗和预处理（非常重要！）**：
   - 检查并处理 NaN 和空值：根据需要使用 df.fillna(0) 或 df.dropna()
   - 确保数据类型正确，避免类型转换错误：使用带 errors='coerce' 的 pd.to_numeric
   - 注意鉴别 index 和 columns 是否有用，如果没有用则要自己删除，因为 index 和 columns 不占用索引，即它们在预览中虽然有，但是是 -1 行和 -1 列
   - 处理 'invalid literal for int() with base 10: \'nan\'' 这类错误
4. 生成数据预览，包括：
   - 文件基本信息
   - 数据形状（行数、列数）
   - 列名列表
   - 行名列表
   - 前10行10列数据预览包括index和columns作为第0行和第0列（使用 df.head(10).to_string()）
   - **特别说明**：明确指出 dataframe 的 index（索引）和 columns（列名）是否包含实际需要的数据
     - 如果 index 或 columns 包含实际数据，说明需要将其转换为普通列
     - 如果只是标签或占位符，说明可以忽略
5. 仅返回预览信息，用 print() 输出
6. 输出格式：直接输出预览信息字符串

**第二步：构建数据接口**
当 current_step = "interface" 时（同时会提供第一步的预览信息 {data_preview}）：
1. 基于第一步的数据预览，理解数据结构
2. **生成数据接口代码（提供所有有用的数据接口！）**：
   - 创建一个可重用的 Python 模块，提供标准的 pyecharts 所需的数据格式
   - **文件读取要健壮**：
     - 对于 CSV 文件，要尝试多种编码：utf-8, gbk, gb2312, gb18030, latin1
     - 使用 try-except 处理可能的错误
   - 该模块应包含**所有可能有用的数据访问函数**，覆盖各种图表类型的需求
   - 函数应该返回标准化的数据结构：
     - **通用数据访问函数**：
       - get_all_columns()：返回所有列名列表
       - get_column_data(column_name_or_index)：返回指定列的数据
       - get_x_y_data(x_col, y_col)：返回 (x_data, y_data) 格式
       - get_multi_series_data(x_col, y_cols)：返回 (x_data, series_list)，series_list 是 [{{'name': '系列名', 'data': [...]}}]
     - **饼图/漏斗图专用**：
       - get_pie_data(name_col, value_col)：返回 [{{'name': '名称', 'value': 数值}}]
       - get_funnel_data(name_col, value_col)：返回 [{{'name': '名称', 'value': 数值}}]
     - **雷达图专用**：
       - get_radar_schema(indicator_names)：返回雷达图指标配置
       - get_radar_data(data_cols)：返回雷达图数据
     - **按列名/索引访问**：
       - get_column_by_name(col_name)：按列名返回数据
       - get_column_by_index(col_index)：按列索引返回数据
   - 确保数据已经清洗和类型转换完成
   - 代码必须完整、可执行，包含必要的导入
   - 在数据接口代码中包含数据清洗步骤
   - **尽可能多地提供有用的函数，让计划智能体有更多选择**
3. 输出格式：
   - 先使用 print() 输出分隔符 "---DATA_INTERFACE_CODE---"
   - 然后输出数据接口代码
   - 同时返回完整的输出字符串

重要要求：
- 代码必须完整且可执行
- 仅返回 Python 代码，不要包含其他文本
- 必须明确说明 index 和 columns 的有用性
- 数据接口代码必须保存为可重用的模块
- 数据接口代码中必须包含完整的数据清洗和预处理步骤

数据清洗示例代码：
```python
# 数据清洗 - 至关重要！
df = df.fillna(0)  # 处理 NaN 值
for col in df.columns:
    if df[col].dtype == 'object':
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
```

仅返回代码，不要其他说明。
"""

agent_debug_chart_prompt ="""
你是一位专门修复图表生成代码的调试专家。

输入信息：
- 原始计划（plan_details）
- 失败代码（failed_code）
- 错误信息（error_message）
- 数据预览（data_preview）
- 数据列 schema（dataset_summary，来自 canonical_dataset）

你的任务是基于上述输入信息，分析错误并修复用于图表生成的 Python 代码。

要求：
1. 仔细分析错误信息（重点看 traceback 最后一行的异常类型 + 相关行号）
2. 确定失败的根本原因（列名错、类型错、数据接口 import 错、pyecharts API 用错等）
3. 修复代码以解决问题
4. 确保修复的代码完整且可执行
5. 仅返回修复的 Python 代码，不包含其他文本
6. 保持原始计划中的相同图表要求（chart_type / chart_title / 数据列/接口函数）

**保存图表约束（与生成阶段一致）**：
- **只调用 `chart.render()`**，不要传 path 参数、不要拼路径、不要 `os.makedirs`
- 输出路径由框架 header 自动注入，任何试图修改保存路径的代码都会被覆盖
- 若原代码把错误归因到"路径不存在 / 找不到文件"，请检查是否误改了 render 调用；直接改回 `chart.render()` 即可

**常见错误速查**：
- `KeyError: '<列名>'`：列名与 dataset_summary 不匹配，用 dataset_summary.columns[].name 里的原始列名
- `ModuleNotFoundError: No module named 'data_preview'`：`sys.path.insert(0, <data_interface_code_file 的父目录>)` 未加或路径错误
- `TypeError: NoneType` / `ValueError` 在数据管道：多为 NaN 未清洗，加 `df.fillna(0)` 或 `pd.to_numeric(..., errors='coerce')`
- pyecharts `TypeError: add_yaxis() missing`：`.add_yaxis(series_name, y_data)` 至少要传两个参数
"""

def get_agent_chart_designer_prompt() -> ChatPromptTemplate:
    return ChatPromptTemplate(
        [
        ("system",agent_chart_designer_prompt),
        ("human","{data_file_path}\n数据表格的相关数据的预览:{data_preview}\n数据接口信息:{data_interface_info}\ncanonical_dataset(权威):\n{canonical_dataset}\n{user_prompt}\n{mcp_prompt}\n{skill_prompt}")
        ]
    ).partial(canonical_dataset="(未提供)")
def get_agent_generate_chart_prompt() -> ChatPromptTemplate:
    return ChatPromptTemplate(
        [
        ("system",agent_generate_chart_prompt),
        ("human","数据文件: {data_file_path}\n数据预览: {data_preview}\n数据列 schema(canonical):\n{dataset_summary}\n计划: {plan_details}\n参考文档: {reference_docs}")
        ]
    ).partial(dataset_summary="(未提供)")
def get_agent_data_preview_prompt(pandas_reference: str = "") -> ChatPromptTemplate:
    return ChatPromptTemplate(
        [
        ("system",agent_data_preview_prompt),
        ("human","数据文件路径: {data_file_path}\n当前步骤: {current_step}\n数据预览: {data_preview}")
        ]
    ).partial(pandas_reference=pandas_reference)

def get_agent_debug_chart_prompt() -> ChatPromptTemplate:
    return ChatPromptTemplate(
        [
        ("system",agent_debug_chart_prompt),
        ("human","计划: {plan_details}\n失败代码:\n{failed_code}\n错误:\n{error_message}\n数据预览:\n{data_preview}\n数据列 schema(canonical):\n{dataset_summary}")
        ]
    ).partial(dataset_summary="(未提供)")


agent_db_query_prompt = """
你是一位精通 SQL 的数据工程师。用户给你数据库 schema 和可视化需求，你需要生成一条只读的 SELECT 语句。

**硬性约束**：
1. **仅允许 SELECT / SHOW / DESC / EXPLAIN / WITH 开头**，禁止任何写入或 DDL（DROP/DELETE/UPDATE/INSERT/CREATE/ALTER/TRUNCATE）。
2. 只用 schema 中出现的表和列，不要虚构。
3. 对结果集大小控制：如果数据量可能很大，主动 GROUP BY 或 LIMIT。
4. 优先聚合、过滤到"可视化友好"的量级（通常 100~10000 行）。
5. 如果用户需求模糊（例如"看看数据"），选择最能反映数据整体特征的一个查询（如 GROUP BY 主要维度 + 主要度量）。

**输出格式**（严格 JSON）：
```json
{{
  "sql": "SELECT ...",
  "explanation": "一句话解释这条 SQL 回答什么问题",
  "expected_columns": ["col1", "col2"]
}}
```

**示例**：
schema:
- sales (12345 rows): id INT PK, date DATE, region VARCHAR, amount DECIMAL
需求："按地区展示销售额"

输出:
```json
{{
  "sql": "SELECT region, SUM(amount) AS total_sales FROM sales GROUP BY region ORDER BY total_sales DESC LIMIT 100",
  "explanation": "按地区聚合销售额，取 top100",
  "expected_columns": ["region", "total_sales"]
}}
```
"""


def get_agent_db_query_prompt() -> ChatPromptTemplate:
    return ChatPromptTemplate(
        [
            ("system", agent_db_query_prompt),
            ("human", "数据库 schema:\n{db_schema}\n\n用户需求:\n{user_prompt}\n\n用户提示的表(可选):\n{hint_table}"),
        ]
    )


agent_db_multi_query_prompt = """
你是一位精通 SQL 和数据可视化的数据工程师。用户给你数据库 schema 和可视化需求，你需要生成**多条独立的 SELECT 语句**，每条 SQL 支撑一个独立的可视化视角（不同的数据集）。

**硬性约束**：
1. **仅允许 SELECT / SHOW / DESC / EXPLAIN / WITH 开头**，禁止任何写入或 DDL（DROP/DELETE/UPDATE/INSERT/CREATE/ALTER/TRUNCATE）
2. 只用 schema 中出现的表和列，不要虚构
3. 每条 SQL 结果集控制在 100~10000 行，主动 GROUP BY / LIMIT
4. 每个 query 应聚焦一个独立的可视化角度：
   - 时间趋势（按 date/month 聚合）
   - 维度分组（按 category/region 分组）
   - top-N 排名
   - 相关性/占比
5. 查询之间**互相独立**，不需要 JOIN 关联（若需要 JOIN 一起可视化，把它写在**同一条** SQL 里）
6. 生成 **{min_queries}~{max_queries}** 条 query。宁少勿多；如果 schema 简单，2~3 条即可
7. 若用户需求模糊，选择最能反映数据整体特征的组合（如按时间/按维度/按类别）

**输出格式**（严格 JSON）：
```json
{{
  "queries": [
    {{
      "sql": "SELECT ...",
      "name": "sales_by_region",
      "explanation": "按地区聚合销售额，展示区域分布",
      "expected_columns": ["region", "total"]
    }},
    {{
      "sql": "SELECT strftime('%Y-%m', date) AS month, SUM(amount) AS total FROM sales GROUP BY month ORDER BY month",
      "name": "sales_by_month",
      "explanation": "按月份聚合销售额，展示时间趋势",
      "expected_columns": ["month", "total"]
    }}
  ]
}}
```

**name 命名规则**：小写下划线，用于 parquet 文件名和 dataset 标识，不要重复。
"""


def get_agent_db_multi_query_prompt() -> ChatPromptTemplate:
    return ChatPromptTemplate(
        [
            ("system", agent_db_multi_query_prompt),
            ("human", "数据库 schema:\n{db_schema}\n\n用户需求:\n{user_prompt}\n\n最多生成 {max_queries} 条 query。"),
        ]
    ).partial(min_queries="2", max_queries="5")


agent_viz_code_completion_prompt = """
你是科学 Python 代码助手。用户会提供一段 Python 代码 + 可视化需求。

**你的任务**：
1. 阅读用户代码，理解已定义的顶层变量、函数、类、import
2. 在**代码末尾追加**一段可视化代码片段（不修改原代码）
3. 优先使用与用户风格一致的库（如果 imports 已含 matplotlib 则用 matplotlib）
4. 如果 `scientific_lib` 显式指定，遵守
5. 需求模糊时选择最直接的一种展示方式

**限制**：
- 只生成 Python 代码，不执行
- 不引入未在标准 numpy/matplotlib/plotly/seaborn/pandas/scipy 范围内的库
- 不做网络访问、文件读写（除保存图片外）
- 不使用 os.system / subprocess

**输出严格 JSON**：
```json
{{
  "snippet": "import matplotlib.pyplot as plt\\n...\\nplt.show()",
  "explanation": "识别到 signal 是长度 1024 的 numpy 一维数组，用 magnitude_spectrum 展示频谱。",
  "libs": ["matplotlib", "numpy"]
}}
```

**注意**：snippet 里的换行用 `\\n`；不要输出 ```python 代码块外壳，只输出 JSON。
"""


def get_agent_viz_code_completion_prompt() -> ChatPromptTemplate:
    return ChatPromptTemplate(
        [
            ("system", agent_viz_code_completion_prompt),
            ("human",
             "用户代码摘要:\n{source_summary}\n\n"
             "用户完整代码:\n```python\n{full_source}\n```\n\n"
             "可视化需求:\n{user_prompt}\n\n"
             "偏好库(可选): {scientific_lib}"),
        ]
    )