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


def _multi_measure_series(tmp_path: Path) -> SemanticSeries:
    df = pd.DataFrame({
        "时间": pd.date_range("2026-01-01", periods=20, freq="s"),
        "设备A温度": [70 + i * 0.1 for i in range(20)],
        "设备B温度": [65 + i * 0.08 for i in range(20)],
    })
    path = tmp_path / "sensor.parquet"
    df.to_parquet(path, index=False)
    shape = compute_series_shape(
        df, "time_series", "时间", ["设备A温度", "设备B温度"]
    )
    return SemanticSeries(
        series_id="factory.设备A温度、设备B温度",
        name="factory.设备A温度、设备B温度",
        axis_kind="time_series",
        row_label_column="时间",
        column_label_columns=["设备A温度", "设备B温度"],
        data_path=str(path),
        source_table="factory",
        description="两台设备温度",
        extra_semantics={"shape": shape},
    )


def _many_measure_series(tmp_path: Path) -> SemanticSeries:
    cols = [f"设备{i:02d}温度" for i in range(1, 21)]
    data = {"时间": pd.date_range("2026-01-01", periods=10, freq="s")}
    for i, col in enumerate(cols):
        data[col] = [60 + i + j * 0.1 for j in range(10)]
    df = pd.DataFrame(data)
    path = tmp_path / "many_sensors.parquet"
    df.to_parquet(path, index=False)
    shape = compute_series_shape(df, "time_series", "时间", cols)
    return SemanticSeries(
        series_id="factory.多设备温度",
        name="factory.多设备温度",
        axis_kind="time_series",
        row_label_column="时间",
        column_label_columns=cols,
        data_path=str(path),
        source_table="factory",
        description="20 台设备温度",
        extra_semantics={"shape": shape},
    )


def _profile() -> SimpleNamespace:
    return SimpleNamespace(
        to_prompt_dict=lambda **kwargs: {"table_name": "单列数值"},
        to_prompt_str=lambda **kwargs: "单列数值：销售额",
    )


class _FailingChat:
    async def arun_with_tools(self, *args, **kwargs):
        raise RuntimeError("429 Endpoint is unavailable")

    async def ainvoke(self, *args, **kwargs):
        raise RuntimeError("429 Endpoint is unavailable")


@pytest.mark.asyncio
async def test_plan_stage_stops_after_explicit_target(tmp_path: Path, monkeypatch):
    """用户明确要 1 张图时，should_stop 在已有 1 个 plan 后返回 True。"""
    import service.pipeline.agent_plan_stage as stage

    series = _series(tmp_path)
    catalog = SeriesCatalog(datasets_dir=str(tmp_path), series=[series])
    model_ = SimpleNamespace(
        user_prompt="画一张图",
        file_paths=[],
        config=None,
        mcp_prompt="",
        skill_prompt="",
    )

    class _StopChat:
        should_stop = None

        async def arun_with_tools(self, *args, **kwargs):
            self.should_stop = kwargs.get("should_stop")
            return {"agent_logs": []}

    class _State:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
            self.plans = [{"plan_id": "1"}]
            self.dropped = []

        def plan_count(self):
            return len(self.plans) + len(self.dropped)

    monkeypatch.setattr(stage, "requested_chart_count", lambda _prompt: 1)
    monkeypatch.setattr(stage, "PlanSessionState", _State)
    monkeypatch.setattr(stage, "build_plan_tool_pool", lambda _state: [])
    monkeypatch.setattr(stage, "diversify_plans", lambda plans, *args, **kwargs: plans)
    monkeypatch.setattr(stage, "_persist_plans", lambda *args, **kwargs: None)

    chat = _StopChat()
    plans = await run_plan_stage(
        chat,
        model_=model_,
        profile=_profile(),
        output_folder=tmp_path,
        task_id=None,
        catalog=catalog,
        agent_logs=[],
    )

    assert plans == [{"plan_id": "1"}]
    assert callable(chat.should_stop)
    assert chat.should_stop() is True


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


@pytest.mark.asyncio
async def test_fallback_trend_keeps_all_measures_in_one_series(tmp_path: Path):
    series = _multi_measure_series(tmp_path)
    catalog = SeriesCatalog(datasets_dir=str(tmp_path), series=[series])
    model_ = SimpleNamespace(
        user_prompt="分析两台设备最近一段时间的温度趋势，画一张折线图",
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

    trend_plans = [p for p in plans if chart_family(p["chart_type"]) == "trend"]
    assert trend_plans, plans
    assert any(
        {"设备A温度", "设备B温度"} <= set(p.get("y_axis") or [])
        for p in trend_plans
    ), trend_plans


@pytest.mark.asyncio
async def test_fallback_caps_many_measure_trend_to_readable_columns(tmp_path: Path):
    series = _many_measure_series(tmp_path)
    catalog = SeriesCatalog(datasets_dir=str(tmp_path), series=[series])
    model_ = SimpleNamespace(
        user_prompt="分析所有设备温度趋势",
        file_paths=[],
        config=None,
        mcp_prompt="",
        skill_prompt="",
    )

    plans = await run_plan_stage(
        _FailingChat(),
        model_=model_,
        profile=_profile(),
        output_folder=tmp_path,
        task_id=None,
        catalog=catalog,
        agent_logs=[],
    )

    trend_plans = [p for p in plans if chart_family(p["chart_type"]) == "trend"]
    assert trend_plans, plans
    assert all(0 < len(p.get("y_axis") or []) <= 8 for p in trend_plans), trend_plans
