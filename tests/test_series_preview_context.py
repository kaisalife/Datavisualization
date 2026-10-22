"""series 预览的上下文保护回归（宽表只展示少量列）。"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from service.data_ingestion.series.models import SemanticSeries, SeriesCatalog

pytestmark = pytest.mark.whitebox


def _wide_series(tmp_path: Path, n: int = 30) -> SemanticSeries:
    columns = [f"设备{i:02d}温度" for i in range(1, n + 1)]
    data = {"时间": pd.date_range("2026-01-01", periods=5, freq="s")}
    for i, column in enumerate(columns):
        data[column] = [60 + i + j * 0.1 for j in range(5)]
    df = pd.DataFrame(data)
    path = tmp_path / "wide.parquet"
    df.to_parquet(path, index=False)
    return SemanticSeries(
        series_id="factory.设备01温度、设备02温度、设备03温度 等30项",
        name="factory.多设备温度",
        axis_kind="time_series",
        row_label_column="时间",
        column_label_columns=columns,
        data_path=str(path),
        source_table="factory",
        description="30 台设备温度",
        extra_semantics={"shape": {"rows": 5, "time_like": True}},
    )


@pytest.mark.asyncio
async def test_get_series_truncates_wide_preview(tmp_path: Path):
    from agent.tools.base import ToolContext
    from service.pipeline.plan_recipe_tools import GetSeriesTool

    series = _wide_series(tmp_path)
    catalog = SeriesCatalog(datasets_dir=str(tmp_path), series=[series])
    tool = GetSeriesTool(catalog)

    output = await tool.call(
        {"series_id": series.series_id}, ToolContext(auto_confirm=True)
    )

    assert output.success is True
    assert "共 30 列" in output.output
    assert "设备01温度" in output.output
    # 第 30 列不应进入预览 JSON，避免上千列把上下文打满
    assert "设备30温度" not in output.output
    assert len(output.output) < 5000


@pytest.mark.asyncio
async def test_preview_series_truncates_wide_preview(tmp_path: Path):
    from agent.tools.base import ToolContext
    from agent.tools.read_table_sample_tool import ReadSeriesSampleTool

    series = _wide_series(tmp_path)
    catalog = SeriesCatalog(datasets_dir=str(tmp_path), series=[series])
    tool = ReadSeriesSampleTool(catalog)

    output = await tool.call(
        {"series_id": series.series_id, "limit": 5},
        ToolContext(auto_confirm=True),
    )

    assert output.success is True
    assert "共 30 列" in output.output
    assert "时间" in output.output
    assert "设备01温度" in output.output
    assert "设备30温度" not in output.output
    assert len(output.output) < 5000


@pytest.mark.asyncio
async def test_narrow_series_preview_keeps_all_columns(tmp_path: Path):
    from agent.tools.base import ToolContext
    from agent.tools.read_table_sample_tool import ReadSeriesSampleTool

    series = _wide_series(tmp_path, n=3)
    catalog = SeriesCatalog(datasets_dir=str(tmp_path), series=[series])
    tool = ReadSeriesSampleTool(catalog)

    output = await tool.call(
        {"series_id": series.series_id, "limit": 5},
        ToolContext(auto_confirm=True),
    )

    assert output.success is True
    assert "共 3 列" not in output.output
    assert "设备03温度" in output.output
