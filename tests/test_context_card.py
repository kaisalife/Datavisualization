"""上下文卡片与对话持久化回归（无 LLM）。"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from Entity import GenerateChartWithPromptResponse
from service.runtime import conversation_store as cs
from service.runtime.context_card import (
    build_context_cards,
    cards_to_prompt_text,
    write_context_cards,
)

pytestmark = pytest.mark.whitebox


def _profile():
    return SimpleNamespace(
        table_name="销售数据",
        source_kind="file",
        row_count=12,
        schema=[{"name": "月份", "type": "VARCHAR"}, {"name": "销售额", "type": "DOUBLE"}],
        series_catalog=SimpleNamespace(series=[object(), object()]),
        degraded=False,
        degraded_reason="",
    )


def _plan(*, with_error: bool = False) -> dict:
    report = {
        "ok": not with_error,
        "errors": ([{"code": "CODE_NAME_ERROR", "message": "name 'foo' is not defined"}]
                   if with_error else []),
        "warnings": [],
    }
    return {
        "plan_id": "p1",
        "plan_name": "月度销售额趋势",
        "chart_title": "2024 年月度销售额",
        "chart_type": "Line",
        "series_id": "销售数据.月度销售额",
        "analysis_task": "trend",
        "x_axis": "月份",
        "y_axis": ["销售额"],
        "assumptions": ["按月份汇总销售额"],
        "ambiguities": [{"description": "求和还是平均", "options": ["总和", "平均"]}],
        "clarification": [
            {"question": "是否只看华东", "options": ["只看华东", "全部区域"]}
        ],
        "confidence": 0.8,
        "generation": {"validation": report},
    }


def test_build_context_cards_covers_request_data_plan_validation_and_artifacts():
    plan = _plan()
    cards = build_context_cards(
        "画月度趋势",
        _profile(),
        [plan],
        [{
            "plan": plan,
            "chart_path": "runtime/charts/x/chart_p1.html",
            "generation": {
                "code_path": "runtime/charts/x/code/code_p1_success.py",
                "attempts": 2,
                "duration_ms": 1234.5,
            },
        }],
        [],
    )
    kinds = [c["kind"] for c in cards]
    assert kinds == ["request", "data", "plan", "workflow", "validation", "artifact"]

    plan_card = next(c for c in cards if c["kind"] == "plan")
    assert plan_card["status"] == "warning"  # 有歧义
    assert any("求和还是平均" in i for i in plan_card["items"])
    assert any("按月份汇总销售额" in i for i in plan_card["items"])
    assert plan_card["meta"]["clarification"]
    assert "是否只看华东" in plan_card["meta"]["clarification"][0]

    workflow = next(c for c in cards if c["kind"] == "workflow")
    assert workflow["status"] == "success"
    assert any("成功 1 个 / 失败 0 个" in i for i in workflow["items"])
    assert any("修复轮次：2 次" in i for i in workflow["items"])

    validation = next(c for c in cards if c["kind"] == "validation")
    assert validation["status"] == "success"

    artifact = next(c for c in cards if c["kind"] == "artifact")
    assert artifact["status"] == "success"
    assert any("chart_p1.html" in i for i in artifact["items"])
    assert any("生成尝试 2 次" in i for i in artifact["items"])
    assert any("生成耗时 1.2 秒" in i for i in artifact["items"])

    text = cards_to_prompt_text(cards)
    assert "当前需求" in text
    assert "月度销售额趋势" in text


def test_validation_card_reports_classified_error():
    plan = _plan(with_error=True)
    cards = build_context_cards(
        "画趋势",
        _profile(),
        [plan],
        [],
        [{"plan": plan, "error": "NameError"}],
    )
    validation = next(c for c in cards if c["kind"] == "validation")
    assert validation["status"] == "error"
    assert any("CODE_NAME_ERROR" in i for i in validation["items"])

    artifact = next(c for c in cards if c["kind"] == "artifact")
    assert artifact["status"] == "error"


def test_write_context_cards(tmp_path: Path):
    cards = build_context_cards("画趋势", None, [], [], [])
    path = write_context_cards(tmp_path, cards)
    assert path == tmp_path / "plans" / "context_cards.json"
    assert path.exists()
    assert "当前需求" in path.read_text(encoding="utf-8")


def test_conversation_store_round_trips_context_cards(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(cs, "_DB_PATH", str(tmp_path / "conversations.db"))
    cs.init_db()
    cid = cs.create_conversation("画趋势")
    cs.complete_conversation(
        cid,
        "success",
        charts=["Line"],
        context_cards=[{"id": "request", "kind": "request", "title": "当前需求"}],
    )
    conv = cs.get_conversation(cid)
    assert conv["status"] == "success"
    assert conv["charts"] == ["Line"]
    assert conv["context_cards"][0]["title"] == "当前需求"


def test_response_model_accepts_context_cards():
    response = GenerateChartWithPromptResponse(
        Charts=["Line"],
        HtmlFilePaths=["a.html"],
        AgentLogs=[],
        Codes=["code"],
        ContextCards=[{"id": "request", "kind": "request"}],
    )
    assert response.ContextCards[0]["kind"] == "request"
