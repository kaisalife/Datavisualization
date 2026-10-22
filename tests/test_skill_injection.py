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


def _category_series(tmp_path: Path) -> SemanticSeries:
    """类目排行 series（11 个类目，1 个度量）——帕累托技能的形态。"""
    labels = [
        "焊点虚焊", "元件偏移", "少锡", "连锡", "立碑", "桥接短路",
        "划伤", "表面划伤", "异物", "端子变形", "锡珠",
    ]
    df = pd.DataFrame({"不良描述": labels, "判定数量": list(range(33, 22, -1))})
    path = tmp_path / "defect.parquet"
    df.to_parquet(path, index=False)
    return SemanticSeries(
        series_id="defect.不良描述",
        name="defect.不良描述",
        axis_kind="category",
        row_label_column="不良描述",
        column_label_columns=["判定数量"],
        data_path=str(path),
        source_table="defect",
        description="不良项排行",
        extra_semantics={
            "shape": {"rows": len(labels), "time_like": False},
            "source_kind": "file",
        },
    )


@pytest.mark.asyncio
async def test_generation_skill_selection_uses_user_prompt_gate(
    tmp_path: Path, monkeypatch,
):
    """require_keywords 技能必须靠用户话术命中；生成阶段不传 user_prompt 时应选不中。"""
    series = _category_series(tmp_path)
    catalog = SeriesCatalog(datasets_dir=str(tmp_path), series=[series])
    plan = {
        "plan_id": "1",
        "plan_name": "不良项排行",
        "chart_type": "Bar",
        "chart_title": "不良项排行",
        "series_id": series.series_id,
        "x_axis": "不良描述",
        "y_axis": ["判定数量"],
        "analysis_task": "comparison",
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

    # 1) 普通话术（无场景关键词）→ 帕累托技能门控拦截，不注入
    await generate_single_chart(
        chat=_FakeChat(),
        plan=plan,
        data_file_path="",
        data_preview="",
        output_folder=tmp_path,
        max_retries=1,
        catalog=catalog,
        user_prompt="对比各城市销售额",
    )
    assert "extend_axis" not in captured["skill_context"]

    # 2) 业务话术命中 → 注入完整技能正文（双轴范式可见）
    await generate_single_chart(
        chat=_FakeChat(),
        plan=plan,
        data_file_path="",
        data_preview="",
        output_folder=tmp_path,
        max_retries=1,
        catalog=catalog,
        user_prompt="帮我做不良项主次因素排列，看帕累托",
    )
    assert "extend_axis" in captured["skill_context"]
    assert "累计占比" in captured["skill_context"]


def test_chart_designer_prompt_carries_skill_index():
    """回退规划路径（无 load_skill 工具）也必须能看到技能索引。"""
    from prompts.chart_designer_prompt import get_agent_chart_designer_prompt

    text = get_agent_chart_designer_prompt().invoke(
        {
            "data_file_path": "",
            "data_preview": "",
            "data_interface_info": "",
            "canonical_dataset": "{}",
            "series_index": "- s1",
            "skill_index": "- gauge-kpi-snapshot: KPI 达成仪表盘",
            "user_chart_config": "",
            "user_prompt": "3号机组完成情况",
            "mcp_prompt": "",
            "skill_prompt": "",
        }
    ).to_string()

    assert "gauge-kpi-snapshot" in text
    assert "skill_index" in text
