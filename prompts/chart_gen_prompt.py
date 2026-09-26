"""图表生成/调试 prompt（从 agent_prompt.py 拆出）。

v4 变更：series 数据契约模式（read_recipe_hint 非空时）：
守护层执行时把从语义 series 加载 df 的代码拼在 LLM 代码开头，LLM 只面对 df（真实预览），
只写变换与绘图；series parquet 路径不进入 LLM 上下文。
"""
from langchain_core.prompts import ChatPromptTemplate

# ============================================================
# 图表生成（每个 plan 单独执行）
# ============================================================

agent_generate_chart_prompt = """
按计划生成单个图表的 pyecharts 代码。

## 数据获取（series 模式，read_recipe_hint 非空时必须遵守）
本计划已选定数据系列。**读取代码已由框架执行**（执行时自动拼在你的代码开头）：
- 已提供全局变量 `df`（从所选 series 的 parquet 加载的 DataFrame）
- **禁止**自己 import duckdb / read_parquet 重新加载 / 建连接 / 写 SELECT / 重新定义 df
- 只写：数据变换（按 transform_hint，用 pandas 在 df 上完成）与 pyecharts 绘图
- read_recipe_hint 中的 df 真实预览即你要用的数据，列名以它为准，直接用
- 若 read_recipe_hint 为"(无)"：忽略本节，直接用输入数据接口 info 取数（自备）

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

输入：plan_details / failed_code / error_message / dataset_summary / read_recipe_hint / user_config

1. 分析错误（traceback 最后一行异常类型 + 行号）
2. 修复代码，保持计划要求（chart_type/chart_title/数据列）
3. 只调 chart.render()（不传 path，框架自动注入）
4. 遵守布局规范（标题/图例防重叠，与生成阶段一致）
5. 仅返回 Python 代码

series 模式（read_recipe_hint 非空时）：
- 读取代码由框架在代码开头提供（df 已从 series 加载），修复时禁止自己写 duckdb/read_parquet 重新加载/重新定义 df
- read_recipe_hint 中的 df 真实预览即你要用的数据，直接基于它修变换与绘图

常见错误：
- KeyError: 列名与 dataset_summary 不匹配，用原始列名
- TypeError/ValueError: NaN 未清洗，加 df.fillna(0) 或 pd.to_numeric(errors='coerce')
- pyecharts add_yaxis: 至少传 (series_name, y_data)
"""


# ============================================================
# 代码调试（生成失败时修复）
# ============================================================

# Prompt 工厂函数
def get_agent_generate_chart_prompt() -> ChatPromptTemplate:
    return ChatPromptTemplate([
        ("system", agent_generate_chart_prompt),
        ("human", "数据文件: {data_file_path}\n数据预览: {data_preview}\n数据列 schema:\n{dataset_summary}\n计划: {plan_details}\nread_recipe_hint: {read_recipe_hint}\n参考文档: {reference_docs}\n用户自定义图表配置: {user_config}")
    ]).partial(dataset_summary="(未提供)", user_config="(未提供)", read_recipe_hint="(无)")


def get_agent_debug_chart_prompt() -> ChatPromptTemplate:
    return ChatPromptTemplate([
        ("system", agent_debug_chart_prompt),
        ("human", "计划: {plan_details}\n失败代码:\n{failed_code}\n错误:\n{error_message}\n数据预览:\n{data_preview}\n数据列 schema:\n{dataset_summary}\nread_recipe_hint: {read_recipe_hint}\n用户自定义图表配置: {user_config}")
    ]).partial(dataset_summary="(未提供)", user_config="(未提供)", read_recipe_hint="(无)")