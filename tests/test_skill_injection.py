"""生成阶段技能注入回归（无 LLM）。"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from service.data_ingestion.series.models import SemanticSeries, SeriesCatalog
from service.pipeline.chart_generator import generate_single_chart
from service.pipeline.chart_sandbox import SandboxResult

pytestmark = pytest.mark.whitebox


class _FakeChat:
    async def ainvoke(self, payload):
        return {"content": "```python\nprint('ok')\n```"}


def _series(tmp_path: Path, *, rows: int = 1500, axis_kind: str = "time_series") -> SemanticSeries:
    df = pd.DataFrame({
        "时间": pd.date_range("2026-01-01", periods=rows, freq="s"),
        "温度": [20 + (i % 10) for i in range(rows)],
    })
    path = tmp_path / "sensor.parquet"
    df.to_parquet(path, index=False)
    return SemanticSeries(
        series_id="factory.温度",
        name="factory.温度",
        axis_kind=axis_kind,
        row_label_column="时间",
        column_label_columns=["温度"],
        data_path=str(path),
        source_table="factory",
        description="车间温度",
        extra_semantics={"shape": {"rows": rows, "time_like": axis_kind == "time_series"}},
    )


def _fake_execute(body, *, charts_folder: Path, plan_id: str):
    charts_folder.mkdir(parents=True, exist_ok=True)
    path = charts_folder / f"chart_{plan_id}.html"
    path.write_text(
        "<html><body><div id='c'></div><script>echarts.init(c)</script></body></html>",
        encoding="utf-8",
    )
    return SandboxResult(
        True,
        "ok",
        str(path),
        path.name,
        data_stats={
            "series_count": 1,
            "types": ["line"],
            "total_points": 10,
            "empty_points": 0,
            "numeric_values": 10,
            "zero_values": 0,
            "has_dataset": False,
            "series": [],
        },
    )


@pytest.mark.asyncio
async def test_generation_injects_high_frequency_skill(
    tmp_path: Path, monkeypatch,
):
    series = _series(tmp_path, rows=1500)
    catalog = SeriesCatalog(datasets_dir=str(tmp_path), series=[series])
    plan = {
        "plan_id": "1",
        "plan_name": "温度趋势",
        "chart_type": "Line",
        "chart_title": "车间温度趋势",
        "series_id": series.series_id,
        "x_axis": "时间",
        "y_axis": ["温度"],
        "analysis_task": "trend",
    }
    captured: dict = {}

    async def fake_invoke(engine, chat, prompt, input_data):
        captured.update(input_data)
        return "```python\nprint('ok')\n```"

    monkeypatch.setattr(
        "service.pipeline.chart_generator.execute_chart_code", _fake_execute
    )
    monkeypatch.setattr(
        "service.pipeline.chart_generator._invoke_llm", fake_invoke
    )

    success, chart_path, code, error = await generate_single_chart(
        chat=_FakeChat(),
        plan=plan,
        data_file_path="",
        data_preview="",
        output_folder=tmp_path,
        max_retries=1,
        catalog=catalog,
    )

    assert success is True, error
    assert chart_path
    assert "高频/大样本时间序列" in captured["skill_context"]
    assert "resample" in captured["skill_context"]


@pytest.mark.asyncio
async def test_generation_injects_financial_skill_for_candlestick(
    tmp_path: Path, monkeypatch,
):
    series = _series(tmp_path, rows=100)
    catalog = SeriesCatalog(datasets_dir=str(tmp_path), series=[series])
    plan = {
        "plan_id": "1",
        "plan_name": "分钟K线",
        "chart_type": "Candlestick",
        "chart_title": "分钟K线",
        "series_id": series.series_id,
        "x_axis": "时间",
        "y_axis": ["温度"],
        "analysis_task": "trend",
    }
    captured: dict = {}

    async def fake_invoke(engine, chat, prompt, input_data):
        captured.update(input_data)
        return "```python\nprint('ok')\n```"

    monkeypatch.setattr(
        "service.pipeline.chart_generator.execute_chart_code", _fake_execute
    )
    monkeypatch.setattr(
        "service.pipeline.chart_generator._invoke_llm", fake_invoke
    )

    success, _, _, error = await generate_single_chart(
        chat=_FakeChat(),
        plan=plan,
        data_file_path="",
        data_preview="",
        output_folder=tmp_path,
        max_retries=1,
        catalog=catalog,
    )

    assert success is True, error
    assert "金融 K 线" in captured["skill_context"]
    assert "[open, close, low, high]" in captured["skill_context"]
