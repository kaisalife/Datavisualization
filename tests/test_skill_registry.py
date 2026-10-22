"""技能渐进式披露回归（无 LLM）。"""
from __future__ import annotations

from pathlib import Path

import pytest

from service.data_ingestion.series.models import SemanticSeries
from service.skills import SkillRegistry
from service.skills.registry import get_skill_registry

pytestmark = pytest.mark.whitebox


def _series(
    tmp_path: Path,
    *,
    rows: int = 5000,
    columns: list[str] | None = None,
    source_kind: str = "file",
) -> SemanticSeries:
    columns = columns or ["温度", "压力"]
    return SemanticSeries(
        series_id="factory.传感器",
        name="factory.传感器",
        axis_kind="time_series",
        row_label_column="时间",
        column_label_columns=columns,
        data_path=str(tmp_path / "sensor.parquet"),
        source_table="factory",
        description="车间传感器时序",
        extra_semantics={
            "shape": {"rows": rows, "time_like": True},
            "source_kind": source_kind,
        },
    )


def test_skill_index_is_compact_and_loads_full_body():
    registry = get_skill_registry()
    index = registry.index_text()

    assert "high-frequency-timeseries" in index
    assert "financial-candlestick" in index
    # 完整正文不应进入索引
    assert "## 生成阶段" not in index
    assert "## 生成阶段" in registry.get("high-frequency-timeseries").body


def test_selects_high_frequency_skill_for_dense_time_series(tmp_path: Path):
    registry = get_skill_registry()
    selected = registry.select(
        plan={"chart_type": "Line", "analysis_task": "trend"},
        series=_series(tmp_path, rows=5000),
    )

    assert any(skill.name == "high-frequency-timeseries" for skill in selected)
    assert all(skill.name != "financial-candlestick" for skill in selected)


def test_small_time_series_does_not_load_high_frequency_skill(tmp_path: Path):
    registry = get_skill_registry()
    selected = registry.select(
        plan={"chart_type": "Line", "analysis_task": "trend"},
        series=_series(tmp_path, rows=100),
    )

    assert selected == []


def test_candlestick_plan_selects_financial_skill(tmp_path: Path):
    registry = get_skill_registry()
    selected = registry.select(
        plan={"chart_type": "Candlestick", "analysis_task": "trend"},
        series=_series(tmp_path, rows=500),
    )

    assert [skill.name for skill in selected] == ["financial-candlestick"]


def test_many_series_plan_selects_many_series_skill(tmp_path: Path):
    registry = get_skill_registry()
    columns = [f"设备{i}" for i in range(1, 13)]
    selected = registry.select(
        plan={"chart_type": "Line", "analysis_task": "trend"},
        series=_series(tmp_path, rows=500, columns=columns),
    )

    assert any(skill.name == "many-series-timeseries" for skill in selected)


def test_document_series_selects_multimodal_skill(tmp_path: Path):
    registry = get_skill_registry()
    selected = registry.select(
        plan={"chart_type": "Bar", "analysis_task": "comparison"},
        series=_series(tmp_path, rows=10, source_kind="document"),
    )

    assert [skill.name for skill in selected] == ["multimodal-extracted-table"]

    file_series = registry.select(
        plan={"chart_type": "Bar", "analysis_task": "comparison"},
        series=_series(tmp_path, rows=10, source_kind="file"),
    )
    assert file_series == []


def test_context_for_plan_injects_only_selected_body(tmp_path: Path):
    registry = get_skill_registry()
    context = registry.context_for_plan(
        plan={"chart_type": "Candlestick", "analysis_task": "trend"},
        series=_series(tmp_path, rows=500),
    )

    assert "金融 K 线" in context
    assert "[open, close, low, high]" in context
    assert "多设备/多指标时序" not in context


# ---------- require_keywords 门控（防形态撞车） ----------


def test_pareto_skill_requires_scenario_keywords(tmp_path: Path):
    """普通 Bar+comparison 排行（城市销售额）不得命中帕累托技能。"""
    registry = get_skill_registry()
    ranking_series = _series(tmp_path, rows=11, columns=["判定数量"], source_kind="file")
    ranking_series = type(ranking_series)(
        **{
            **{f: getattr(ranking_series, f) for f in ranking_series.__dataclass_fields__},
            "axis_kind": "category",
            "extra_semantics": {
                "shape": {"rows": 11, "time_like": False},
                "source_kind": "file",
            },
        }
    )

    plain = registry.select(
        plan={"chart_type": "Bar", "analysis_task": "comparison"},
        series=ranking_series,
        user_prompt="对比各城市销售额",
    )
    assert all(skill.name != "pareto-quality" for skill in plain)

    pareto = registry.select(
        plan={"chart_type": "Bar", "analysis_task": "comparison"},
        series=ranking_series,
        user_prompt="做主次因素排列找不良项帕累托",
    )
    assert any(skill.name == "pareto-quality" for skill in pareto)


def test_require_keywords_meta_is_read_from_frontmatter():
    skill = get_skill_registry().get("pareto-quality")
    assert skill is not None
    assert skill.metadata.get("require_keywords") in {True, "true"}
    assert "帕累托" in skill.metadata.get("user_keywords")


def test_empty_skill_directory_is_safe(tmp_path: Path):
    registry = SkillRegistry(tmp_path)
    assert registry.index_text() == "(无技能)"
    assert registry.select(plan={"chart_type": "Line"}) == []
    assert registry.get("missing") is None


@pytest.mark.asyncio
async def test_load_skill_tool_returns_full_body_on_demand():
    from agent.tools.base import ToolContext
    from service.pipeline.plan_recipe_tools import LoadSkillTool

    tool = LoadSkillTool()
    output = await tool.call(
        {"name": "financial-candlestick"}, ToolContext(auto_confirm=True)
    )
    assert output.success is True
    assert "K 线" in output.output

    missing = await tool.call(
        {"name": "not-a-skill"}, ToolContext(auto_confirm=True)
    )
    assert missing.success is False
    assert "技能不存在" in missing.error


def test_generation_prompt_accepts_selected_skill_context():
    from prompts.chart_gen_prompt import get_agent_generate_chart_prompt

    prompt = get_agent_generate_chart_prompt().invoke({
        "data_file_path": "",
        "data_preview": "",
        "plan_details": "{}",
        "reference_docs": "(无)",
        "skill_context": "SKILL_MARKER：先聚合再画图",
    })
    text = "\n".join(str(m.content) for m in prompt.to_messages())
    assert "SKILL_MARKER" in text


def test_debug_prompt_accepts_selected_skill_context():
    from prompts.chart_gen_prompt import get_agent_debug_chart_prompt

    prompt = get_agent_debug_chart_prompt().invoke({
        "plan_details": "{}",
        "failed_code": "",
        "error_message": "",
        "data_preview": "",
        "skill_context": "DEBUG_SKILL_MARKER",
    })
    text = "\n".join(str(m.content) for m in prompt.to_messages())
    assert "DEBUG_SKILL_MARKER" in text


def test_planning_prompt_contains_skill_index():
    from prompts.agent_planning_prompt import build_planning_prompt

    prompt = build_planning_prompt().invoke({
        "user_prompt": "分析传感器趋势",
        "profile_str": "(未提供)",
        "series_index": "(未提供)",
        "skill_index": "- high-frequency-timeseries: 高频时序",
    })
    text = "\n".join(str(m.content) for m in prompt.to_messages())

    assert "load_skill" in text
    assert "high-frequency-timeseries" in text
    assert "不要一次加载全部技能" in text


def test_multiline_user_keywords_are_parsed_as_list():
    """frontmatter 的折行关键词列表必须解析成 list，不能退化成字符串。"""
    registry = get_skill_registry()

    for name in ("pareto-quality", "gauge-kpi-snapshot", "spc-stability"):
        keywords = registry.get(name).metadata.get("user_keywords")
        assert isinstance(keywords, list), (name, type(keywords), keywords)
        assert len(keywords) >= 5
        assert all(isinstance(item, str) and "," not in item for item in keywords)


def test_frontmatter_multiline_list_stops_at_next_key():
    from service.skills.registry import _parse_frontmatter

    meta = _parse_frontmatter(
        "chart_types: [Bar]\n"
        "user_keywords: [甲, 乙,\n"
        "  丙]\n"
        "min_rows: 3"
    )

    assert meta["user_keywords"] == ["甲", "乙", "丙"]
    assert meta["min_rows"] == 3


def test_require_keywords_matches_phrases_not_characters():
    """关键词门控必须整词匹配：普通排行不能被帕累托技能误命中。"""
    skill = get_skill_registry().get("pareto-quality")
    common = dict(
        chart_type="Bar",
        analysis_task="comparison",
        time_like=False,
        rows=10,
        series_count=1,
    )

    assert not skill.matches(user_prompt="各城市销售额排行", **common)
    assert skill.matches(user_prompt="不良项主次因素分析", **common)
