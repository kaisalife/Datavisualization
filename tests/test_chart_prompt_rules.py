"""图表生成 prompt 的硬性规则测试（无需 LLM）。

真实链路里模型曾把 `opts.InitOpts` 写成裸 `InitOpts(...)`，触发 NameError 并浪费
一轮 debug。这里把"选项类必须带 opts. 前缀"钉成回归测试。
"""
from __future__ import annotations

import re

import pytest

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
