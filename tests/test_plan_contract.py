"""图表计划契约与校验报告回归（无 LLM）。

对应设计文档 D1/D2/D5：
- ChartPlan 携带 analysis_task / ambiguities / assumptions / confidence / clarification
- 守护层把结构化校验报告写回 plan["validation"]
- 旧 prompt / 旧 plan 缺字段时只降级，不阻塞
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from Entity.plan_models import parse_plans
from prompts.agent_planning_prompt import build_planning_prompt
from prompts.chart_designer_prompt import get_agent_chart_designer_prompt
from service.data_ingestion.series.models import SemanticSeries, SeriesCatalog
from service.pipeline.plan_validator import ensure_plan_contract, validate_one_plan

pytestmark = pytest.mark.whitebox


def _series(tmp_path: Path) -> SemanticSeries:
    df = pd.DataFrame({
        "月份": ["1月", "2月", "3月"],
        "销售额": [100, 120, 150],
    })
    path = tmp_path / "sales.parquet"
    df.to_parquet(path, index=False)
    return SemanticSeries(
        series_id="sales.月度",
        name="月度销售额",
        axis_kind="time_series",
        row_label_column="月份",
        column_label_columns=["销售额"],
        data_path=str(path),
        source_table="sales",
        description="测试 series",
    )


def _plan(series_id: str = "sales.月度", **overrides) -> dict:
    plan = {
        "plan_id": "p1",
        "plan_name": "月度趋势",
        "chart_type": "Line",
        "chart_title": "月度销售额趋势",
        "series_id": series_id,
        "x_axis": "月份",
        "y_axis": ["销售额"],
        "analysis_task": "trend",
        "assumptions": ["按月份汇总销售额"],
        "confidence": 0.9,
        "ambiguities": [],
        "clarification": [],
    }
    plan.update(overrides)
    return plan


def test_parse_plan_contract_fields_and_aliases():
    plans = parse_plans({
        "plans": [{
            "planId": "1",
            "planName": "趋势",
            "chartType": "Line",
            "chartTitle": "月度趋势",
            "seriesId": "sales.月度",
            "xAxis": "月份",
            "yAxis": ["销售额"],
            "analysisTask": "TREND",
            "ambiguities": {"kind": "聚合", "description": "求和还是平均"},
            "assumptions": "按总和聚合",
            "confidence": 90,
            "clarification": {"question": "是否按总和？", "options": ["总和", "平均"]},
        }]
    })

    plan = plans[0]
    assert plan.analysis_task == "trend"
    assert plan.confidence == pytest.approx(0.9)
    assert plan.assumptions == ["按总和聚合"]
    assert plan.ambiguities[0]["kind"] == "聚合"
    assert plan.clarification[0]["question"] == "是否按总和？"


def test_ensure_plan_contract_normalizes_and_reports_bad_confidence():
    report = {
        "degraded": False,
        "warnings": [],
        "errors": [],
    }
    plan = ensure_plan_contract({
        "plan_id": "p1",
        "analysis_task": " Comparison ",
        "assumptions": "按城市汇总",
        "ambiguities": "字段含义不清",
        "confidence": "85",
    }, report)

    assert plan["analysis_task"] == "comparison"
    assert plan["assumptions"] == ["按城市汇总"]
    assert plan["ambiguities"] == ["字段含义不清"]
    assert plan["confidence"] == pytest.approx(0.85)
    assert report["warnings"] == []

    bad = ensure_plan_contract({"confidence": "很高"}, report)
    assert bad["confidence"] is None
    assert report["warnings"]


def test_validate_one_plan_writes_structured_report(tmp_path: Path):
    series = _series(tmp_path)
    catalog = SeriesCatalog(datasets_dir=str(tmp_path), series=[series])
    logs: list[str] = []
    plan = _plan()

    assert validate_one_plan(plan, catalog, None, logs) is True
    report = plan["validation"]
    assert report["ok"] is True
    assert report["stage"] == "plan"
    assert report["degraded"] is False
    assert report["contract_complete"] is True
    assert report["requires_clarification"] is False
    assert report["assumptions"] == ["按月份汇总销售额"]


def test_validate_one_plan_reports_unknown_columns(tmp_path: Path):
    series = _series(tmp_path)
    catalog = SeriesCatalog(datasets_dir=str(tmp_path), series=[series])
    logs: list[str] = []
    plan = _plan(x_axis="不存在的列")

    assert validate_one_plan(plan, catalog, None, logs) is False
    report = plan["validation"]
    assert report["ok"] is False
    assert report["errors"][0]["code"] == "UNKNOWN_COLUMNS"
    assert "月份" in report["errors"][0]["hint"]


def test_validate_one_plan_degrades_bad_series(tmp_path: Path):
    series = _series(tmp_path)
    catalog = SeriesCatalog(datasets_dir=str(tmp_path), series=[series])
    logs: list[str] = []
    plan = _plan(series_id="missing.series")

    assert validate_one_plan(plan, catalog, None, logs) is True
    assert plan["series_id"] == series.series_id
    assert plan["degraded"] is True
    assert plan["validation"]["degraded"] is True
    assert plan["validation"]["warnings"]


def test_validate_one_plan_rejects_unknown_chart_type(tmp_path: Path):
    series = _series(tmp_path)
    catalog = SeriesCatalog(datasets_dir=str(tmp_path), series=[series])
    logs: list[str] = []
    plan = _plan(chart_type="Magic")

    assert validate_one_plan(plan, catalog, None, logs) is False
    assert plan["validation"]["errors"][0]["code"] == "UNSUPPORTED_CHART_TYPE"


def test_plan_prompts_can_be_formatted_with_contract_fields():
    planning = build_planning_prompt().invoke({
        "user_prompt": "画趋势",
        "profile_str": "(未提供)",
        "series_index": "(未提供)",
    })
    planning_text = "\n".join(str(m.content) for m in planning.to_messages())
    assert "analysis_task" in planning_text
    assert "confidence" in planning_text

    designer = get_agent_chart_designer_prompt().invoke({
        "data_file_path": "",
        "data_preview": "",
        "data_interface_info": "",
        "canonical_dataset": "(未提供)",
        "series_index": "(未提供)",
        "user_chart_config": "(未提供)",
        "user_prompt": "画趋势",
        "mcp_prompt": "",
        "skill_prompt": "",
    })
    designer_text = "\n".join(str(m.content) for m in designer.to_messages())
    assert "ambiguities" in designer_text
    assert "clarification" in designer_text
