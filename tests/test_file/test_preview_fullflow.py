"""数据预览全流程集成测试（v4，语义 series）。

覆盖 ingestion 完整链路：文件 -> 语义 series 拆分 -> 落盘 manifest+parquet，
并用多种数据形态验证拆分/兜底泛化能力。

运行（真实拓扑，addopts 默认排除 needs_llm，需清空）：
    .venv/Scripts/python.exe -m pytest tests/test_file -o addopts="" -m "needs_llm and integration"
"""
from __future__ import annotations

from pathlib import Path

import pytest

from service.data_ingestion.series import load_series_df
from service.pipeline.plan_validator import validate_one_plan
from tests.test_file.helpers import assert_artifacts, run_preview_fullflow

pytestmark = [pytest.mark.needs_llm, pytest.mark.integration]


async def test_normal_table_fullflow(real_chat, normal_csv: Path, tmp_path: Path):
    """正常多列表：拆分出语义 series（时间序列/类别比较）+ 落盘。"""
    task_dir = tmp_path / "task_normal"
    result = await run_preview_fullflow(normal_csv, task_dir, real_chat)

    profile = result["profile"]
    assert profile.row_count == 4
    assert {c["name"] for c in profile.schema} == {"年份", "地区", "销售额"}
    assert profile.session_dir

    catalog = result["catalog"]
    assert result["n_series"] >= 1
    # 含时间序列（年份->销售额）
    ts = [s for s in catalog.series if s.axis_kind == "time_series"]
    assert ts, f"未拆分出时间序列: {[s.series_id for s in catalog.series]}"
    # 每个 series 可加载且非空
    for s in catalog.series:
        assert len(load_series_df(s)) > 0

    assert_artifacts(result)


async def test_single_column_text_fullflow(real_chat, single_col_text: Path, tmp_path: Path):
    """单列文本表：无法按列语义拆分时兜底 generic series（不丢信息）。"""
    task_dir = tmp_path / "task_text"
    result = await run_preview_fullflow(single_col_text, task_dir, real_chat)

    assert len(result["profile"].schema) == 1
    assert result["profile"].schema[0]["name"] == "数据库：年度数据"

    # 兜底 generic series = 整表，可加载
    assert result["n_series"] >= 1
    assert any(s.axis_kind == "generic" for s in result["series"])
    assert_artifacts(result)


async def test_real_wide_table_fullflow(real_chat, wide_data: Path, tmp_path: Path):
    """真实 stats gov 年度数据（tab+逗号混排的单列文本）：兜底 generic，不崩。"""
    task_dir = tmp_path / "task_wide"
    result = await run_preview_fullflow(wide_data, task_dir, real_chat)

    assert len(result["profile"].schema) >= 1
    assert result["profile"].row_count >= 1

    # 至少产出一条可加载 series（宽表/单列文本走 generic 兜底）
    assert result["n_series"] >= 1
    for s in result["series"]:
        assert len(load_series_df(s)) >= 1
    assert_artifacts(result)


async def test_series_usable_by_plan_agent(real_chat, normal_csv: Path, tmp_path: Path):
    """拆分出的 series 可直接被计划阶段引用：加载有数据 + 校验器可接受。"""
    result = await run_preview_fullflow(normal_csv, tmp_path / "task_usable", real_chat)
    catalog = result["catalog"]
    ts = next((s for s in catalog.series if s.axis_kind == "time_series"), catalog.series[0])

    df = load_series_df(ts)
    assert df is not None and len(df) > 0

    # 引用 series 的行标签列 + 列标签列可过计划校验
    assert validate_one_plan(
        {"plan_id": "1", "chart_type": "Bar", "series_id": ts.series_id,
         "x_axis": ts.row_label_column, "y_axis": list(ts.column_label_columns)},
        catalog, result["profile"], [],
    )