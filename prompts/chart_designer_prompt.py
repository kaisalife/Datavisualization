"""图表规划 prompt（从 agent_prompt.py 拆出）。

v4 变更：plan 增加 series_id / transform_hint 字段，
规划时必须从 series_index（可用数据系列索引）中选定数据系列。
"""
from langchain_core.prompts import ChatPromptTemplate

chart_designer_prompt = """
你是数据可视化规划专家。基于数据语义特征，为每个图表生成一个 plan（含类型/字段映射/布局/数据系列），供生成阶段逐个执行。

## 输入
- canonical_dataset（权威）：列 name/dtype/semantic_role(time/measure/dimension/id)、stats、preview_rows、semantic_hints.detected_patterns
- series_index（权威）：可用数据系列索引（series_id + 语义类型 + 说明），每个 plan 必须从中选定一个
- data_file_path、data_preview：辅助
- user_chart_config：用户图表配置偏好（可选）
- 用户需求

## 规划原则
1. 从 canonical_dataset.schema 读列名和 semantic_role
2. semantic_role="time" -> 首选 x_axis；"measure" -> 首选 y_axis/value；"dimension" -> 分组/category
3. detected_patterns 含 time_series -> 优先 Line/Area；含 categorical_comparison -> 优先 Bar/Pie
4. 根据用户需求规划 2-4 个图表，每个一个 plan
5. 数据系列选择：时间序列类选 time_series 系列；对比/占比类选 categorical_comparison 系列；不确定选 generic 系列
6. 若所选系列返回的列不足以完成图表（如需增长率），在 transform_hint 写明变换公式
7. 图表类型按数据形态选，不要所有图都用 Bar：
   - 时间序列且时间点 ≥3 -> **Line/Area**，不要画 Bar/Pie（≤2 个时间点才可用 Bar）；
   - 2-6 个非负类别、单指标 -> Bar 看对比；"占比/构成"需求用 Pie；
   - 7-20 个非负类别 -> Bar（按指标降序）；需要构成角度时另配 Treemap；
     >20 个类别 -> Bar 取 Top 10 + 其他，不要用饼图；
   - 两指标关系 -> Scatter/Heatmap；单指标分布 -> Histogram/Boxplot；
   - 多指标横向比较 -> 分组/堆叠 Bar 或 Radar。
   - 用户明确点名类型时遵从用户；没有点名时按数据形态选，不要被"对比"二字带偏。
8. 2-4 个图要覆盖不同分析角度（趋势/对比/构成/分布/关系），不要用同一 series、同一指标重复出图；
   同一 series + 同一指标的 Bar 最多一张，不要提交"同一数据换个排序/标题"的第二张柱状图。
9. 用户指定图表数量（如"画两个图"）时严格不超过；数据只支持一个角度时宁可少画，不要硬造类型。
10. chart_title 必须具体（含指标 + 维度，必要时含时间/单位），不要写「图表1」「数据展示」。
11. analysis_task 从 trend / comparison / composition / distribution / relationship 中选一个。
12. 用户需求存在会影响结果的歧义（字段、时间范围、聚合方式、图表类型）时，写入 ambiguities；
    高影响歧义在 clarification 中给出候选问题，不要静默选择后当作确定结果。
13. assumptions 只写实际采用的假设及理由；confidence 用 0-1 表示计划整体置信度。

## 数据访问（语义 series 为主）
数据已拆分为多个语义 series 落盘，生成阶段按 plan.series_id 指定的系列加载 df。
plan 的数据字段填**该系列的真实列名**（行标签列 / 列标签列），data_interface.available = false。

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
    "series_id": "源名.系列名（必须从 series_index 中选）",
    "transform_hint": "加载后还需做的变换公式，无则空字符串",
    "x_axis": "该系列的行标签列名",
    "y_axis": ["该系列的列标签列名"],
    "use_column_names": true,
    "data_interface": {{"available": false}},
    "execution_order": 1,
    "layout": {{
      "legend_pos": "bottom",
      "grid_top": "8%",
      "grid_bottom": "12%"
    }},
    "analysis_task": "trend | comparison | composition | distribution | relationship",
    "ambiguities": [{{"kind": "字段/时间/聚合/类型", "description": "哪里存在多种理解", "options": ["候选1", "候选2"]}}],
    "assumptions": ["实际采用的假设及理由"],
    "confidence": 0.0,
    "clarification": [{{"question": "需要用户确认的问题", "options": ["选项1", "选项2"]}}]
  }}]
}}
```

## chart_type 可选值
Line, Bar, Scatter, Pie, Area, Histogram, Boxplot, Heatmap, Candlestick, Radar, Funnel, Gauge, Treemap, WordCloud, Graph, Parallel, Sankey, ThemeRiver

## 必填字段
plan_id, plan_name, chart_type, chart_title, chart_reason, series_id, transform_hint, x_axis, y_axis, use_column_names, data_interface, execution_order, layout, analysis_task, ambiguities, assumptions, confidence, clarification
"""


def get_agent_chart_designer_prompt() -> ChatPromptTemplate:
    """图表规划 prompt 工厂（输入变量含 series_index，缺省"(未提供)"）。"""
    return ChatPromptTemplate([
        ("system", chart_designer_prompt),
        (
            "human",
            "{data_file_path}\n数据预览:{data_preview}\n数据接口信息:{data_interface_info}\n"
            "canonical_dataset(权威):\n{canonical_dataset}\n"
            "数据系列索引(series_index,权威):\n{series_index}\n"
            "用户自定义图表配置:{user_chart_config}\n{user_prompt}\n{mcp_prompt}\n{skill_prompt}",
        ),
    ]).partial(
        canonical_dataset="(未提供)",
        user_chart_config="(未提供)",
        series_index="(未提供)",
    )