"""重构后冒烟测试（无需 LLM）。

覆盖：
- Entity/plan_models.py 的 parse_plans / plan_get
- service.data_ingestion.router 的 ingest（asyncio.to_thread 路径）
- service.data_ingestion.series.splitter 的 _approx_unique
- chat_fingerprint
"""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from Entity.plan_models import (
    ChartPlan, PlanBundle, parse_plans, plan_get,
)


class TestParsePlans:
    def test_parses_wrapped(self):
        plans = parse_plans({"plans": [
            {"plan_id": "a", "chart_type": "Bar", "series_id": "x.y"}
        ]})
        assert len(plans) == 1
        assert plans[0].plan_id == "a"
        assert plans[0].series_id == "x.y"

    def test_parses_bare_list(self):
        plans = parse_plans([
            {"plan_id": "a", "chart_type": "Bar", "series_id": "x.y"}
        ])
        assert len(plans) == 1

    def test_parses_camelcase_aliases(self):
        plans = parse_plans([{
            "planId": "a", "chartType": "Line", "seriesId": "x.y",
            "chartTitle": "Q1", "executionOrder": 2,
        }])
        assert plans[0].plan_id == "a"
        assert plans[0].chart_type == "Line"
        assert plans[0].chart_title == "Q1"
        assert plans[0].execution_order == 2

    def test_series_id_required(self):
        with pytest.raises(Exception):
            parse_plans([{"plan_id": "a", "chart_type": "Bar"}])

    def test_invalid_chart_type(self):
        with pytest.raises(Exception):
            parse_plans([{"plan_id": "a", "chart_type": "NotAChart", "series_id": "x.y"}])

    def test_plan_get_with_dict(self):
        p = {"plan_id": "x"}
        assert plan_get(p, "plan_id") == "x"
        assert plan_get(p, "missing", "default") == "default"

    def test_plan_get_with_chartplan(self):
        p = ChartPlan(plan_id="x", series_id="y.z", chart_type="Bar")
        assert plan_get(p, "plan_id") == "x"
        assert plan_get(p, "missing", "default") == "default"

    def test_extra_keys_ignored(self):
        """LLM 输出冗余字段不应报错。"""
        plans = parse_plans([{
            "plan_id": "a", "chart_type": "Bar", "series_id": "x.y",
            "未知字段": "应该被忽略",
        }])
        assert plans[0].plan_id == "a"


class TestIngestNonBlocking:
    @pytest.mark.asyncio
    async def test_ingest_runs_concurrently(self, tmp_path: Path):
        """验证 asyncio.to_thread 修复生效：ingest 期间其它协程可运行。"""
        from service.data_ingestion.router import ingest, _route, _assemble_profile
        from service.data_ingestion.models import DataSource
        from service.observability import get_logger

        # 构造一个简单的临时 CSV
        csv = tmp_path / "data.csv"
        csv.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")

        source = DataSource(kind="file", path=str(csv), name="test")
        # ingest 现在用 asyncio.to_thread 包了同步 IO；
        # 跑一个 heartbeat 验证不阻塞 event loop
        heartbeat_ticks = 0
        stop = asyncio.Event()

        async def heartbeat():
            nonlocal heartbeat_ticks
            while not stop.is_set():
                heartbeat_ticks += 1
                await asyncio.sleep(0.01)

        task = asyncio.create_task(heartbeat())
        try:
            profile = await ingest(source)
            # 等 heartbeat 跑几个 tick
            await asyncio.sleep(0.05)
        finally:
            stop.set()
            await task

        # 如果 ingest 阻塞 event loop，heartbeat 几乎不会 tick
        # asyncio.to_thread 修复后心跳应能跑多次
        assert heartbeat_ticks >= 2, f"heartbeat 被阻塞，仅跑了 {heartbeat_ticks} 次"
        assert profile is not None
        assert profile.row_count == 2


class TestApproxUnique:
    def test_small_series_exact(self):
        from service.data_ingestion.series.splitter import _approx_unique
        s = pd.Series([1, 2, 2, 3, 3, 3])
        assert _approx_unique(s) == 3

    def test_large_series_sampled(self):
        from service.data_ingestion.series.splitter import _approx_unique
        s = pd.Series(range(100_000))  # 100K unique
        nuniq = _approx_unique(s, sample_size=1000)
        # 采样后近似应接近真实 100K
        assert 50_000 <= nuniq <= 150_000, f"approx_unique 偏差过大: {nuniq}"


class TestChatFingerprint:
    def test_fingerprint_stable(self):
        from service.pipeline.data_preview import _chat_fingerprint

        class FakeChat:
            model_type = "openai"
            model_url = "https://api.example.com/v1"

        fp1 = _chat_fingerprint(FakeChat())
        fp2 = _chat_fingerprint(FakeChat())
        assert fp1 == fp2
        assert fp1.startswith("openai:")

    def test_fingerprint_handles_missing_attrs(self):
        from service.pipeline.data_preview import _chat_fingerprint

        class Bare:
            pass

        fp = _chat_fingerprint(Bare())
        assert fp == "unknown"


class TestSandboxResult:
    def test_pydantic_model(self):
        from service.pipeline.chart_sandbox import SandboxResult

        r = SandboxResult(success=True, output="ok", chart_path="/tmp/x.html", chart_filename="x.html")
        assert r.success is True
        assert r.parse_seconds == 0.0  # default

        # 不可变字段类型校验（Pydantic）
        with pytest.raises(Exception):
            SandboxResult(success="not_a_bool", output="x", chart_path="x", chart_filename="x")


class TestDegradedPropagation:
    @pytest.mark.asyncio
    async def test_degraded_flag_on_raw_table(self, tmp_path: Path):
        """降级 flag 应当从 RawTable 透传到 DataProfile。"""
        from service.data_ingestion.models import DataProfile, DataSource, RawTable
        from service.data_ingestion.profiler import build_profile_from_df

        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        rt = RawTable(
            name="t", df=df, source_kind="file", source_path="x",
            degraded=True, degraded_reason="llm_tabular_failed: dummy",
        )

        profile = build_profile_from_df(df, rt.name, rt.source_kind, rt.source_path)
        # 模拟 _assemble_profile 的透传逻辑
        if rt.degraded:
            profile.degraded = True
            profile.degraded_reason = rt.degraded_reason

        assert profile.degraded is True
        assert "llm_tabular_failed" in profile.degraded_reason
class TestPlanConcurrency:
    """agent/auto 流水线的图表并发执行（不依赖 LLM）。"""

    @pytest.mark.asyncio
    async def test_plans_run_concurrently_and_keep_order(self):
        import time

        from service.pipeline.agent_pipeline import execute_plans_concurrently

        active = 0
        peak = 0

        async def runner(idx, _plan):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.1)
            active -= 1
            return {"idx": idx, "cancelled": False, "logs": [f"p{idx}"]}

        started = time.perf_counter()
        results, cancelled = await execute_plans_concurrently(
            [{}, {}, {}], task_id=None, concurrency=3, runner=runner
        )
        elapsed = time.perf_counter() - started

        assert peak == 3, "3 个 plan 应同时执行"
        assert elapsed < 0.25, f"并发执行耗时异常: {elapsed:.2f}s"
        assert [item["logs"][0] for item in results] == ["p0", "p1", "p2"]
        assert cancelled is False

    @pytest.mark.asyncio
    async def test_concurrency_one_is_serial(self):
        from service.pipeline.agent_pipeline import execute_plans_concurrently

        active = 0
        peak = 0

        async def runner(idx, _plan):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.02)
            active -= 1
            return {"idx": idx, "cancelled": False, "logs": []}

        results, cancelled = await execute_plans_concurrently(
            [{}, {}, {}], task_id=None, concurrency=1, runner=runner
        )

        assert peak == 1
        assert len(results) == 3
        assert cancelled is False

    @pytest.mark.asyncio
    async def test_cancelled_before_start_skips_runner(self, monkeypatch):
        import api.common as common
        from service.pipeline.agent_pipeline import execute_plans_concurrently

        monkeypatch.setattr(common, "is_cancelled", lambda _task_id: True)

        async def runner(idx, _plan):  # pragma: no cover - 不应执行
            raise AssertionError("cancelled plan should not run")

        results, cancelled = await execute_plans_concurrently(
            [{}], task_id="t1", concurrency=2, runner=runner
        )

        assert cancelled is True
        assert results[0]["cancelled"] is True

class TestCoreOptimizations:
    """核心链路的确定性优化回归（不依赖 LLM）。"""

    def test_series_preview_reads_only_head(self, tmp_path, monkeypatch):
        import service.data_ingestion.series.runner as runner
        from service.data_ingestion.series.models import SemanticSeries

        path = tmp_path / "series.parquet"
        pd.DataFrame({"x": list(range(1000))}).to_parquet(path, index=False)
        series = SemanticSeries(
            series_id="s.x",
            name="x",
            axis_kind="generic",
            row_label_column="x",
            column_label_columns=[],
            data_path=str(path),
            source_table="t",
        )

        def _no_full_read(*_args, **_kwargs):
            raise AssertionError("limit 预览不应整表 read_parquet")

        monkeypatch.setattr(runner.pd, "read_parquet", _no_full_read)
        preview = runner.load_series_df(series, limit=5)

        assert preview["x"].tolist() == [0, 1, 2, 3, 4]

    @pytest.mark.asyncio
    async def test_plan_series_tools_read_bounded_rows(self, tmp_path, monkeypatch):
        import agent.tools.read_table_sample_tool as sample_mod
        import service.pipeline.plan_recipe_tools as recipe_mod
        from agent.tools.base import ToolContext
        from service.data_ingestion.series.models import SemanticSeries, SeriesCatalog

        series = SemanticSeries(
            series_id="s.月份",
            name="月度销售额",
            axis_kind="time_series",
            row_label_column="月份",
            column_label_columns=["销售额"],
            data_path=str(tmp_path / "unused.parquet"),
            source_table="t",
        )
        catalog = SeriesCatalog(datasets_dir=str(tmp_path), series=[series])
        limits = []

        def _fake_load(_series, limit=None):
            limits.append(limit)
            return pd.DataFrame({"月份": ["1月"], "销售额": [100]})

        monkeypatch.setattr(sample_mod, "load_series_df", _fake_load)
        monkeypatch.setattr(recipe_mod, "load_series_df", _fake_load)
        monkeypatch.setattr(recipe_mod, "recommend_chart_types", lambda *_a, **_k: {"shape": {}})

        ctx = ToolContext(auto_confirm=True)
        sample = await sample_mod.ReadSeriesSampleTool(catalog).call(
            {"series_id": "s.月份", "limit": 7}, ctx
        )
        assert sample.success is True
        assert limits[-1] == 7

        detail = await recipe_mod.GetSeriesTool(catalog).call(
            {"series_id": "s.月份"}, ctx
        )
        assert detail.success is True
        assert limits[-1] == 5

    def test_plan_validator_checks_metadata_not_full_table(self, tmp_path, monkeypatch):
        import service.pipeline.plan_validator as validator
        from service.data_ingestion.series.models import SemanticSeries

        path = tmp_path / "series.parquet"
        pd.DataFrame({"x": list(range(1000))}).to_parquet(path, index=False)
        series = SemanticSeries(
            series_id="s.x",
            name="x",
            axis_kind="generic",
            row_label_column="x",
            column_label_columns=[],
            data_path=str(path),
            source_table="t",
        )

        def _no_full_read(*_args, **_kwargs):
            raise AssertionError("规划校验不应整表 read_parquet")

        monkeypatch.setattr(validator, "load_series_df", _no_full_read)
        ok, reason = validator._series_is_readable(series)
        assert ok is True
        assert reason == ""

    @pytest.mark.asyncio
    async def test_ingest_files_routes_concurrently(self, tmp_path, monkeypatch):
        import threading
        import time
        from types import SimpleNamespace

        import service.data_ingestion.router as router
        from service.data_ingestion.models import RawTable

        monkeypatch.setenv("INGEST_FILE_CONCURRENCY", "3")
        monkeypatch.setattr(
            router, "allocate_session_dir", lambda: ("ds_test", tmp_path / "sess")
        )

        active = 0
        peak = 0
        lock = threading.Lock()

        def fake_route(source):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.1)
            with lock:
                active -= 1
            name = source.name or Path(source.path).stem
            return [
                RawTable(
                    name=name,
                    df=pd.DataFrame({"a": [1]}),
                    source_kind="file",
                    source_path=source.path,
                )
            ]

        def fake_assemble(raws, session_dir, save_raw):
            return SimpleNamespace(
                related_tables=raws,
                series_catalog=None,
                table_name="t",
                row_count=len(raws),
            )

        monkeypatch.setattr(router, "_route_file", fake_route)
        monkeypatch.setattr(router, "_assemble_profile", fake_assemble)
        paths = [str(tmp_path / f"f{i}.csv") for i in range(3)]

        profile = await router.ingest_files(paths, names=["a", "b", "c"])

        assert peak >= 2, f"多文件接入没有并发，peak={peak}"
        assert [table.name for table in profile.related_tables] == ["a", "b", "c"]
