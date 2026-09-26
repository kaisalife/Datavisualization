"""阶段 3 series 生成诊断（真实模型，v4）。

用 splitter 产出的语义 series，阶段 3 生成 pyecharts 图表。
（宽表/单列文本经 splitter 兜底为 generic series 后仍可出图。）

运行：.venv/Scripts/python.exe -m pytest tests/test_file -o addopts="" -m "needs_llm and integration"
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from service.data_ingestion import DataSource, ingest
from service.pipeline.chart_generator import generate_single_chart

pytestmark = [pytest.mark.needs_llm, pytest.mark.integration]


async def test_stage3_generate_on_series(real_agent, wide_data: Path, tmp_path: Path):
    """阶段 3：基于 splitter 产出的 series 生成趋势图，验证能否出图。"""
    profile = await ingest(DataSource(kind="file", path=str(wide_data), name="年度数据"))
    catalog = profile.series_catalog
    assert catalog is not None and catalog.series, "无 series 目录"

    # 取第一条 series（兜底 generic 亦可），用其行/列标签列作 x/y
    series = catalog.series[0]
    x_col = series.row_label_column
    y_cols = list(series.column_label_columns)

    plan = {
        "plan_id": "1", "plan_name": "数据趋势", "chart_type": "Line",
        "chart_title": "数据趋势",
        "series_id": series.series_id,
        "x_axis": x_col, "y_axis": y_cols,
    }
    t0 = time.time()
    from prompts.chart_gen_prompt import get_agent_generate_chart_prompt

    success, chart_path, code, error = await generate_single_chart(
        real_agent, plan, str(wide_data), "", tmp_path, max_retries=2,
        catalog=catalog,
        generate_prompt=get_agent_generate_chart_prompt(),
    )
    elapsed = time.time() - t0
    assert success, f"阶段3 生成失败（{elapsed:.0f}s）: {error}"
    assert Path(chart_path).exists() and Path(chart_path).stat().st_size > 0
    # 产物自包含：注入版代码无 duckdb / 含 series 加载
    saved = (tmp_path / "code" / "code_1_success.py").read_text(encoding="utf-8")
    assert "duckdb" not in saved
    assert "read_parquet" in saved