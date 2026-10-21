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
- width/height -> opts.InitOpts(width=..., height=...)
- theme -> opts.InitOpts(theme=ThemeType.DARK)
- color/palette -> set_series_opts/itemstyle
- 默认：opts.InitOpts(width="900px", height="500px") + ThemeType.LIGHT

## 导入与命名（必须）
- 固定导入：`from pyecharts import options as opts` 和 `from pyecharts.charts import ...`
- 主题要单独导入：`from pyecharts.globals import ThemeType`；
  **`opts.ThemeType` 不存在**，写 `theme=ThemeType.LIGHT`（不是 `opts.ThemeType.LIGHT`）
- 所有选项类**一律带 `opts.` 前缀**：`opts.InitOpts` / `opts.TitleOpts` / `opts.LegendOpts` /
  `opts.GridOpts` / `opts.LabelOpts` / `opts.AxisOpts`
- **禁止省略 `opts.` 前缀**（省略后就是未定义的名字，必然 NameError）

## 布局（防标题/图例重叠，必须遵守）
- 标题：opts.TitleOpts(pos_top="2%", pos_left="center")
- 图例（plan_details.layout.legend_pos）：
  - "top"/series≤4：opts.LegendOpts(pos_top="2%", pos_right="3%", orient="horizontal")
  - "bottom"/series>4：opts.LegendOpts(pos_bottom="2%", pos_left="center", orient="horizontal")
- **Grid 边距只能通过 Grid 容器设置**：
  `Grid(init_opts=opts.InitOpts(...)).add(chart, grid_opts=opts.GridOpts(pos_top=..., pos_bottom=..., pos_left="8%", pos_right="5%"))`
  `chart.set_global_opts()` **不接受 grid_opts**（传了会 TypeError）
- Pie：center=["50%","55%"], radius=["30%","60%"]
- 多 series：set_series_opts(label_opts=opts.LabelOpts(is_show=False))

## 视觉质量（必须遵守，框架还会做确定性兜底）
- **数据标签**：只有数据点 ≤20 且系列 ≤2 时显示数值；超过就
  `set_series_opts(label_opts=opts.LabelOpts(is_show=False))`，不要用密密麻麻的标签填满画布。
  显示时位置必须写清楚：柱状图 `position="top"`，横向柱状图 `position="right"`，
  折线图 `position="top"`，散点 `position="right"`，饼图 `position="outside"`；
  堆叠柱状图用 `position="inside"`。
- **数值可读性**：大数字用千分位，百分比保留 1 位小数；金额等带量纲的指标必须把单位写进
  轴名或副标题（如「销售额（万元）」），不要只写「数值」或「金额」。
- **轴名**：数值轴写清指标 + 单位；分类轴含义不直观时写轴名。轴名不是图例的替代品。
- **类目排序**：类别对比按指标从高到低排序；时间序列按时间升序；用户明确指定顺序时以用户为准。
- **柱宽**：柱状图调用 `add_yaxis(..., bar_max_width=42)`，类目很少时也不要出现占满画布的宽柱子。
  **pyecharts 2.1 没有 `BarOpts` / `LineOpts` 选项类**，柱宽、折线点标记都用 `add_yaxis` 参数。
- **长标签**：类目名较长或类目数 >12 时用
  `opts.AxisOpts(axislabel_opts=opts.LabelOpts(rotate=45))`；≤20 类可 `interval=0`，
  更多时交给 ECharts 自动间隔，避免标签叠在一起。
- **折线**：数据点 >30 时 `add_yaxis(..., is_symbol_show=False)`，避免点标记糊成一片；
  单系列可加淡色面积（`areastyle_opts=opts.AreaStyleOpts(opacity=0.12)`）。
- **饼图**：`Pie().add(..., radius=["32%","58%"], center=["50%","55%"],
  is_avoid_label_overlap=True, label_opts=opts.LabelOpts(position="outside", formatter="{{b}}: {{d}}%"))`；
  类别 >15 时隐藏标签、保留图例和 tooltip。
- **图例**：横向图例不得与标题重叠；标题长或系列多时优先放底部居中。
- **配色**：同一批图表里同类指标使用同一颜色，不要每个图换一套主题色。

## 类型实现约定
- `Area`：用 `Line` 绘制，并给每个 `add_yaxis` 传
  `areastyle_opts=opts.AreaStyleOpts(opacity=0.15)`；不要 import 不存在的 Area 类。
- `Histogram`：pyecharts 2.1 没有 Histogram 类。用 `pd.cut` 对指标分箱、统计频数后，
  用 `Bar` 绘制（标题仍按 plan 写"分布/直方图"），不要写 `from pyecharts.charts import Histogram`。
- `Boxplot`：用 `from pyecharts.charts import Boxplot`；单指标分布时
  `add_xaxis([指标名])`，`add_yaxis(指标名, Boxplot.prepare_data([数值列表]))`，
  不要把原始数值直接塞进 `add_yaxis`。
- `Treemap`：pyecharts 的类名是 `TreeMap`（大写 M），用
  `from pyecharts.charts import TreeMap`；数据传 `[{{"value": 数值, "name": 类别}}]`；
  类名不要写成 `Treemap`（会 ImportError），也不要在类别很多时改用看不清的饼图。
- `Heatmap`：用 `HeatMap`，数据传 `[x_index, y_index, value]`，并设置 visualmap。
- 其他类型严格按 RAG 参考文档的真实 API 写，拿不准时优先用 Bar/Line/Pie/Scatter。

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
4. 遵守布局与视觉质量规范（标题/图例防重叠、标签位置、轴名单位、排序、柱宽，与生成阶段一致）
5. 仅返回 Python 代码

series 模式（read_recipe_hint 非空时）：
- 读取代码由框架在代码开头提供（df 已从 series 加载），修复时禁止自己写 duckdb/read_parquet 重新加载/重新定义 df
- read_recipe_hint 中的 df 真实预览即你要用的数据，直接基于它修变换与绘图

常见错误：
- KeyError: 列名与 dataset_summary 不匹配，用原始列名
- TypeError/ValueError: NaN 未清洗，加 df.fillna(0) 或 pd.to_numeric(errors='coerce')
- pyecharts add_yaxis: 至少传 (series_name, y_data)
- NameError: InitOpts/TitleOpts/LabelOpts 没加 `opts.` 前缀；选项类一律写 `opts.XxxOpts(...)`
- TypeError: set_global_opts() 不接受 grid_opts -> 改用 `Grid(...).add(chart, grid_opts=opts.GridOpts(...))`
- AttributeError: opts.ThemeType 不存在 -> `from pyecharts.globals import ThemeType`
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