"""生成阶段 ValidationReport / GenerationResult 回归（无 LLM）。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from service.pipeline import generation_validation as gv
from service.pipeline.chart_generator import generate_single_chart
from service.pipeline.chart_sandbox import SandboxResult

pytestmark = pytest.mark.whitebox


class _FakeChat:
    async def ainvoke(self, payload):
        return {"content": "```python\nprint('ok')\n```"}


def _plan() -> dict:
    return {
        "plan_id": "p1",
        "plan_name": "测试图",
        "chart_type": "Line",
        "chart_title": "测试趋势",
        "series_id": "",
        "x_axis": "月份",
        "y_axis": ["销售额"],
    }


def _fake_execute_factory(*, ok: bool, html: str = "", error: str = ""):
    def _fake(body, *, charts_folder: Path, plan_id: str):
        if not ok:
            return SandboxResult(False, error, "", f"chart_{plan_id}.html")
        charts_folder.mkdir(parents=True, exist_ok=True)
        path = charts_folder / f"chart_{plan_id}.html"
        path.write_text(html, encoding="utf-8")
        return SandboxResult(True, "ok", str(path), path.name)

    return _fake


@pytest.mark.asyncio
async def test_generate_single_chart_writes_generation_result_on_success(
    tmp_path: Path, monkeypatch,
):
    monkeypatch.setattr(
        "service.pipeline.chart_generator.execute_chart_code",
        _fake_execute_factory(ok=True, html="<html><body><div id='c'></div><script>echarts.init(c)</script></body></html>"),
    )
    plan = _plan()
    output = tmp_path / "out"

    success, chart_path, code, error = await generate_single_chart(
        chat=_FakeChat(),
        plan=plan,
        data_file_path="",
        data_preview="",
        output_folder=output,
        max_retries=1,
    )

    assert success is True
    assert chart_path and Path(chart_path).exists()
    assert error == ""
    generation = plan["generation"]
    assert generation["ok"] is True
    assert generation["attempts"] == 1
    assert generation["validation"]["ok"] is True
    assert generation["code_path"].endswith("code_p1_success.py")
    artifact = output / "plans" / "generation_p1.json"
    assert artifact.exists()
    saved = json.loads(artifact.read_text(encoding="utf-8"))
    assert saved["plan_id"] == "p1"
    assert saved["validation"]["ok"] is True


@pytest.mark.asyncio
async def test_generate_single_chart_records_classified_runtime_error(
    tmp_path: Path, monkeypatch,
):
    monkeypatch.setattr(
        "service.pipeline.chart_generator.execute_chart_code",
        _fake_execute_factory(
            ok=False,
            error="Traceback (most recent call last):\nNameError: name 'foo' is not defined",
        ),
    )
    plan = _plan()
    output = tmp_path / "out"

    success, chart_path, code, error = await generate_single_chart(
        chat=_FakeChat(),
        plan=plan,
        data_file_path="",
        data_preview="",
        output_folder=output,
        max_retries=1,
    )

    assert success is False
    assert chart_path == ""
    assert "NameError" in error
    report = plan["generation"]["validation"]
    assert report["ok"] is False
    assert report["errors"][0]["code"] == "CODE_NAME_ERROR"
    assert report["errors"][0]["repairable"] is True
    assert (output / "code" / "code_p1_failed.py").exists()
    assert (output / "plans" / "generation_p1.json").exists()


@pytest.mark.asyncio
async def test_generate_single_chart_rejects_empty_or_non_chart_html(
    tmp_path: Path, monkeypatch,
):
    monkeypatch.setattr(
        "service.pipeline.chart_generator.execute_chart_code",
        _fake_execute_factory(ok=True, html="<html><body>no chart here</body></html>"),
    )
    plan = _plan()
    output = tmp_path / "out"

    success, chart_path, code, error = await generate_single_chart(
        chat=_FakeChat(),
        plan=plan,
        data_file_path="",
        data_preview="",
        output_folder=output,
        max_retries=1,
    )

    assert success is False
    assert "CODE_HTML_INVALID" in error
    assert plan["generation"]["validation"]["errors"][0]["code"] == "CODE_HTML_INVALID"


def test_classify_runtime_error_has_stable_codes_and_repairability():
    code, message, hint, repairable = gv.classify_runtime_error(
        "SyntaxError: invalid syntax"
    )
    assert code == "CODE_SYNTAX"
    assert message.startswith("SyntaxError")
    assert hint
    assert repairable is True

    code, _, _, repairable = gv.classify_runtime_error("安全检查失败：禁止写入文件")
    assert code == "CODE_SECURITY_REJECTED"
    assert repairable is False

    code, _, _, _ = gv.classify_runtime_error("KeyError: '利润'")
    assert code == "CODE_FIELD_NOT_FOUND"


def test_html_validation_issues(tmp_path: Path):
    assert gv.html_validation_issues("")[0]["code"] == "CODE_HTML_MISSING"

    empty = tmp_path / "empty.html"
    empty.write_text("", encoding="utf-8")
    assert gv.html_validation_issues(empty)[0]["code"] == "CODE_HTML_INVALID"

    good = tmp_path / "good.html"
    good.write_text("<html><script>echarts.init(el)</script></html>", encoding="utf-8")
    assert gv.html_validation_issues(good) == []


def test_write_generation_result_sanitizes_plan_id(tmp_path: Path):
    result = gv.build_generation_result(
        plan_id="../evil/p1",
        ok=True,
        attempts=1,
        duration_ms=12.3,
    )
    path = gv.write_generation_result(tmp_path, result)
    assert path.parent == tmp_path / "plans"
    assert ".." not in path.name
    assert path.name.startswith("generation_")
