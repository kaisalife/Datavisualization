"""图表生成 prompt 的硬性规则测试（无需 LLM）。

真实链路里模型曾把 `opts.InitOpts` 写成裸 `InitOpts(...)`，触发 NameError 并浪费
一轮 debug。这里把"选项类必须带 opts. 前缀"钉成回归测试。
"""
from __future__ import annotations

import re

import pytest

from prompts.agent_planning_prompt import planning_system_prompt
from prompts.chart_designer_prompt import chart_designer_prompt
from prompts.chart_gen_prompt import agent_debug_chart_prompt, agent_generate_chart_prompt

pytestmark = pytest.mark.whitebox

_OPTION_CLASSES = [
    "InitOpts",
    "TitleOpts",
    "LegendOpts",
    "GridOpts",
    "LabelOpts",
    "AxisOpts",
    "TooltipOpts",
]


@pytest.mark.parametrize(
    "prompt_text",
    [agent_generate_chart_prompt, agent_debug_chart_prompt],
    ids=["generate", "debug"],
)
@pytest.mark.parametrize("option", _OPTION_CLASSES)
def test_option_classes_are_prefixed_with_opts(prompt_text: str, option: str):
    """prompt 里不允许出现裸 `InitOpts(`，只能是 `opts.InitOpts(`。"""
    pattern = re.compile(rf"(?<![\w.]){option}\(")
    assert not pattern.search(prompt_text), f"发现裸调用 {option}(，必须写 opts.{option}(..."


def test_generate_prompt_requires_opts_import():
    assert "from pyecharts import options as opts" in agent_generate_chart_prompt


def test_generate_prompt_has_visual_quality_rules():
    """视觉质量规则必须写进 prompt，不能只靠渲染后兜底。"""
    for keyword in (
        "数据标签",
        "千分位",
        "bar_max_width",
        "轴名",
        "从高到低",
        "rotate=45",
        "tooltip",
    ):
        assert keyword in agent_generate_chart_prompt, f"缺少视觉质量规则: {keyword}"


@pytest.mark.parametrize(
    "prompt_text",
    [agent_generate_chart_prompt, agent_debug_chart_prompt],
    ids=["generate", "debug"],
)
def test_prompt_option_classes_exist_in_pyecharts(prompt_text: str):
    """prompt 里提到的 opts.XxxOpts 必须在当前 pyecharts 版本真实存在。"""
    import pyecharts.options as pyecharts_options

    names = set(re.findall(r"opts\.([A-Za-z_][A-Za-z0-9_]*Opts)\b", prompt_text))
    names.discard("XxxOpts")  # 调试 prompt 里的占位示例
    missing = sorted(name for name in names if not hasattr(pyecharts_options, name))
    assert not missing, f"prompt 使用了不存在的 pyecharts 选项类: {missing}"


def test_generate_prompt_avoids_nonexistent_pyecharts_option_classes():
    """pyecharts 2.1 没有 opts.BarOpts / opts.LineOpts，不能教模型写出必然 AttributeError 的代码。"""
    assert "opts.BarOpts" not in agent_generate_chart_prompt
    assert "opts.LineOpts" not in agent_generate_chart_prompt
    assert "bar_max_width=42" in agent_generate_chart_prompt
    assert "is_symbol_show=False" in agent_generate_chart_prompt
    assert "is_avoid_label_overlap=True" in agent_generate_chart_prompt


def test_generate_prompt_explains_boxplot_api():
    """推荐会落到 Boxplot，prompt 必须说明 prepare_data，避免把原始值直接传给 add_yaxis。"""
    assert "from pyecharts.charts import Boxplot" in agent_generate_chart_prompt
    assert "Boxplot.prepare_data" in agent_generate_chart_prompt
    assert "同一个 x 类目" in agent_generate_chart_prompt


def test_generate_prompt_uses_real_treemap_class_name():
    """pyecharts 的类名是 TreeMap（大写 M），写成 Treemap 会直接 ImportError。"""
    assert "from pyecharts.charts import TreeMap" in agent_generate_chart_prompt
    assert "from pyecharts.charts import Treemap" not in agent_generate_chart_prompt


def test_designer_prompt_requires_varied_chart_types():
    """规划阶段要避免所有图都用 Bar，并给出图表选择口径。"""
    for keyword in (
        "时间序列且时间点 ≥3",
        "7-20 个非负类别",
        "Top 10",
        "占比/构成",
        "同一 series",
        "画两个图",
        "同一指标重复出图",
    ):
        assert keyword in chart_designer_prompt, f"规划 prompt 缺少: {keyword}"


def test_planning_agent_prompt_is_data_driven():
    """agent 规划 prompt 必须按数据形态选类型，并限制重复柱状图/超数量。"""
    for keyword in (
        "≥3 个时间点",
        "2-6 个非负类别",
        "7-20 个非负类别",
        "同一 series + 同一指标",
        "画两个图",
        "趋势 / 对比 / 构成 / 分布 / 关系",
        "不要因为\"对比\"两个字",
    ):
        assert keyword in planning_system_prompt, f"planning prompt 缺少: {keyword}"


def test_generate_prompt_template_can_be_formatted():
    """新增的 JSON 示例必须转义花括号，否则 ChatPromptTemplate 会把它当变量。"""
    from prompts.chart_gen_prompt import get_agent_generate_chart_prompt

    prompt = get_agent_generate_chart_prompt()
    rendered = prompt.invoke({
        "data_file_path": "dummy",
        "data_preview": "",
        "plan_details": "{}",
        "reference_docs": "",
        "dataset_summary": "(未提供)",
        "user_config": "(未提供)",
        "read_recipe_hint": "(无)",
    }).to_string()
    assert "Treemap" in rendered
    assert '\"value\"' in rendered
