"""图表丰富度端到端回归（真实模型）：较多类别时 Bar + Treemap 都能生成。

默认测试集排除 needs_llm；显式运行：

    .venv/Scripts/python.exe -m pytest tests/test_file/test_chart_variety_e2e.py \
        -o addopts="" -m "needs_llm and integration" -q
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from service.data_ingestion import DataSource, ingest
from service.pipeline.agent_pipeline import run_agent_pipeline
from service.pipeline.chart_recommend import chart_family, normalize_chart_type

pytestmark = [pytest.mark.needs_llm, pytest.mark.integration]


@pytest.fixture
def many_cities_csv(tmp_path: Path) -> Path:
    path = tmp_path / "多城市销售.csv"
    rows = [
        ("城市", "销售额"),
        ("北京", 980), ("上海", 870), ("广州", 760), ("深圳", 620),
        ("杭州", 580), ("成都", 540), ("武汉", 510), ("南京", 480),
        ("西安", 450), ("重庆", 420),
    ]
    path.write_text(
        "\n".join(f"{city},{value}" for city, value in rows) + "\n",
        encoding="utf-8",
    )
    return path


async def test_many_categories_generate_bar_and_treemap(
    real_agent, many_cities_csv: Path, tmp_path: Path
):
    profile = await ingest(
        DataSource(kind="file", path=str(many_cities_csv), name="多城市销售")
    )
    model_ = SimpleNamespace(
        user_prompt="分析各城市销售额：画两个图，对比各城市销售额，并看销售额构成",
        file_paths=[str(many_cities_csv)],
        config=None,
        mcp_prompt="",
        skill_prompt="",
        model_type="deepseek",
    )

    result = await run_agent_pipeline(
        real_agent, model_, profile, tmp_path, task_id=None, max_iterations=18
    )
    logs = result["agent_logs"]

    assert result["successful_charts"], "未产出任何图表:\n" + "\n".join(logs[-8:])
    assert len(result["successful_charts"]) == 2, "\n".join(logs[-8:])

    chart_types = [
        normalize_chart_type((chart.get("plan") or {}).get("chart_type", ""))
        for chart in result["successful_charts"]
    ]
    families = {chart_family(t) for t in chart_types}
    assert "comparison" in families
    assert "composition" in families
    assert "treemap" in chart_types, chart_types

    for chart in result["successful_charts"]:
        html = Path(chart["chart_path"])
        assert html.exists() and html.stat().st_size > 0
        generation = chart.get("generation") or {}
        assert generation.get("ok") is True
        data = (generation.get("validation") or {}).get("data") or {}
        if normalize_chart_type((chart.get("plan") or {}).get("chart_type", "")) == "treemap":
            assert data.get("types") == ["treemap"], data


@pytest.fixture
def high_frequency_sensor_csv(tmp_path: Path) -> Path:
    """3000 行、每秒一条的双设备温度数据，模拟车间高频时序。"""
    path = tmp_path / "车间温度.csv"
    lines = ["时间,设备A温度,设备B温度"]
    for i in range(3000):
        minute, second = divmod(i, 60)
        hour, minute = divmod(minute, 60)
        a = 70 + 8 * (i / 3000) + (i % 17) * 0.08
        b = 65 + 5 * (i / 3000) + (i % 23) * 0.06
        lines.append(
            f"2026-01-01 {hour:02d}:{minute:02d}:{second:02d},"
            f"{a:.2f},{b:.2f}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


async def test_high_frequency_sensor_chart_stays_readable(
    real_agent, high_frequency_sensor_csv: Path, tmp_path: Path
):
    profile = await ingest(
        DataSource(
            kind="file", path=str(high_frequency_sensor_csv), name="车间温度"
        )
    )
    model_ = SimpleNamespace(
        user_prompt="分析两台设备最近一小时的温度趋势，注意数据量很大，画一张可读的折线图",
        file_paths=[str(high_frequency_sensor_csv)],
        config=None,
        mcp_prompt="",
        skill_prompt="",
        model_type="deepseek",
    )

    result = await run_agent_pipeline(
        real_agent, model_, profile, tmp_path, task_id=None, max_iterations=16
    )
    logs = result["agent_logs"]

    assert result["successful_charts"], "未产出任何图表:\n" + "\n".join(logs[-8:])
    chart = result["successful_charts"][0]
    plan = chart.get("plan") or {}
    assert normalize_chart_type(plan.get("chart_type", "")) in {"line", "area"}
    # 用户明确说“两台设备”，同一张图必须同时包含 A/B，而不是只画第一列
    assert {"设备A温度", "设备B温度"} <= set(plan.get("y_axis") or []), plan
    html = Path(chart["chart_path"])
    assert html.exists() and html.stat().st_size > 0

    generation = chart.get("generation") or {}
    assert generation.get("ok") is True
    data = (generation.get("validation") or {}).get("data") or {}
    assert 0 < int(data.get("total_points") or 0) <= 1500, data
    names = {item.get("name") for item in data.get("series") or []}
    assert {"设备A温度", "设备B温度"} <= names, data


@pytest.fixture
def single_numeric_csv(tmp_path: Path) -> Path:
    """没有行标签的单列观测值：应走分布，而不是类别柱状图。"""
    values = [
        98, 102, 97, 105, 110, 99, 101, 108, 95, 112,
        100, 104, 96, 107, 103, 109, 94, 111, 106, 113,
        99, 102, 98, 250,
    ]
    path = tmp_path / "单列销售额.csv"
    lines = ["销售额"] + [str(value) for value in values]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


async def test_single_numeric_generates_distribution_chart(
    real_agent, single_numeric_csv: Path, tmp_path: Path
):
    profile = await ingest(
        DataSource(kind="file", path=str(single_numeric_csv), name="单列销售额")
    )
    model_ = SimpleNamespace(
        user_prompt="分析这批销售额的分布，重点看集中趋势和异常值，画一张最合适的图",
        file_paths=[str(single_numeric_csv)],
        config=None,
        mcp_prompt="",
        skill_prompt="",
        model_type="deepseek",
    )

    result = await run_agent_pipeline(
        real_agent, model_, profile, tmp_path, task_id=None, max_iterations=16
    )
    logs = result["agent_logs"]

    assert result["successful_charts"], "未产出任何图表:\n" + "\n".join(logs[-8:])
    chart_types = [
        normalize_chart_type((chart.get("plan") or {}).get("chart_type", ""))
        for chart in result["successful_charts"]
    ]
    assert any(t in {"histogram", "boxplot"} for t in chart_types), chart_types

    for chart in result["successful_charts"]:
        html = Path(chart["chart_path"])
        assert html.exists() and html.stat().st_size > 0
        generation = chart.get("generation") or {}
        assert generation.get("ok") is True
        data = (generation.get("validation") or {}).get("data") or {}
        assert data.get("total_points", 0) > 0, data

