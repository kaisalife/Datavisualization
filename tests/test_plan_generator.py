"""固定 plan 生成路径的 dict 归一化回归（无 LLM）。

`parse_plans` 返回 ChartPlan；执行/校验/上下文卡片层统一用 dict。
这里守住 generate_chart_plans 的返回契约，避免重新引入 BaseModel 无法
json.dump / 无法写回 generation 的问题。
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from service.pipeline.plan_generator import generate_chart_plans

pytestmark = pytest.mark.whitebox


class _FakeEngine:
    async def run_prompt(self, prompt):
        return json.dumps({
            "plans": [{
                "plan_id": "1",
                "plan_name": "月度趋势",
                "chart_type": "Line",
                "chart_title": "月度销售额趋势",
                "series_id": "sales.月度",
                "x_axis": "月份",
                "y_axis": ["销售额"],
                "analysis_task": "trend",
                "assumptions": ["按月份汇总销售额"],
                "confidence": 0.9,
                "ambiguities": [],
                "clarification": [],
            }]
        }, ensure_ascii=False)


@pytest.mark.asyncio
async def test_generate_chart_plans_returns_json_serializable_dicts(
    tmp_path: Path, monkeypatch,
):
    monkeypatch.setattr(
        "service.pipeline.plan_generator.get_project_memory", lambda: ""
    )
    model_ = SimpleNamespace(
        user_prompt="画月度趋势",
        mcp_prompt="",
        skill_prompt="",
    )
    logs: list[str] = []

    plans = await generate_chart_plans(
        _FakeEngine(),
        model_=model_,
        profile=None,
        data_preview="",
        data_file_path="",
        output_folder=tmp_path,
        user_chart_config_json="(未提供)",
        agent_logs=logs,
    )

    assert len(plans) == 1
    plan = plans[0]
    assert isinstance(plan, dict)
    assert plan["chart_type"] == "Line"
    assert plan["analysis_task"] == "trend"
    assert plan["assumptions"] == ["按月份汇总销售额"]
    # 后续 generation 写回与 JSON 落盘都要求普通 dict
    plan["generation"] = {"ok": True, "attempts": 1}
    json.dumps(plan, ensure_ascii=False)
    assert (tmp_path / "plan_response.txt").exists()
    assert (tmp_path / "all_plans.json").exists()
