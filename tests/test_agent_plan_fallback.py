"""LLM 规划失败时的确定性 fallback 回归（无 LLM）。"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from service.data_ingestion.series.models import SemanticSeries, SeriesCatalog
from service.data_ingestion.series.shape import compute_series_shape
from service.pipeline.agent_plan_stage import run_plan_stage
from service.pipeline.chart_recommend import chart_family

pytestmark = pytest.mark.whitebox


def _series(tmp_path: Path) -> SemanticSeries:
    df = pd.DataFrame({
        "销售额": [
            98, 102, 97, 105, 110, 99, 101, 108, 95, 112,
            100, 104, 96, 107, 103, 109, 94, 111, 106, 113,
        ]
    })
    path = tmp_path / "single_numeric.parquet"
    df.to_parquet(path, index=False)
    shape = compute_series_shape(df, "generic", None, ["销售额"])
    return SemanticSeries(
        series_id="sales.单列数值",
        name="sales.单列数值",
        axis_kind="generic",
        row_label_column=None,
        column_label_columns=["销售额"],
        data_path=str(path),
        source_table="t",
        description="测试系列",
        extra_semantics={"shape": shape},
    )


def _profile() -> SimpleNamespace:
    return SimpleNamespace(
        to_prompt_dict=lambda: {"table_name": "单列数值"},
        to_prompt_str=lambda: "单列数值：销售额",
    )


class _FailingChat:
    async def arun_with_tools(self, *args, **kwargs):
        raise RuntimeError("429 Endpoint is unavailable")

    async def ainvoke(self, *args, **kwargs):
        raise RuntimeError("429 Endpoint is unavailable")


@pytest.mark.asyncio
async def test_plan_stage_falls_back_to_deterministic_catalog_plans(
    tmp_path: Path,
):
    series = _series(tmp_path)
    catalog = SeriesCatalog(datasets_dir=str(tmp_path), series=[series])
    model_ = SimpleNamespace(
        user_prompt="分析这批销售额的分布",
        file_paths=[],
        config=None,
        mcp_prompt="",
        skill_prompt="",
    )
    logs: list[str] = []

    plans = await run_plan_stage(
        _FailingChat(),
        model_=model_,
        profile=_profile(),
        output_folder=tmp_path,
        task_id=None,
        catalog=catalog,
        agent_logs=logs,
    )

    assert plans, "LLM 失败时也必须产出数据驱动的 plan"
    assert any(chart_family(plan["chart_type"]) == "distribution" for plan in plans)
    assert all(plan.get("series_id") == series.series_id for plan in plans)
    assert all(plan.get("validation", {}).get("ok") for plan in plans)
    assert any("确定性计划" in line for line in logs)
    assert (tmp_path / "all_plans.json").exists()
