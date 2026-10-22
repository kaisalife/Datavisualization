"""规划 agent 数据视图工具：describe / run_view → 系列注册 → plan 校验通过。"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from agent.tools.base import ToolContext
from service.data_ingestion.models import RawTable
from service.data_ingestion.series import build_series_catalog
from service.data_ingestion.series.models import SeriesCatalog
from service.pipeline.plan_state import PlanSessionState
from service.pipeline.plan_view_tool import (
    DescribeDatasetTool,
    RunViewInput,
    RunViewTool,
    register_view_series,
)
from service.pipeline.plan_validator import validate_one_plan


@pytest.fixture
def session(tmp_path: Path) -> Path:
    """已接入的会话目录：raw 明细 + identity series。"""
    d = tmp_path / "ds_11aa22bb33cc"
    d.mkdir()
    df = pd.DataFrame(
        {
            "城市": ["北京", "北京", "上海", "上海", "合计"],
            "月份": ["1 月", "2 月", "1 月", "2 月", "3 月"],
            "销售额": [100.0, 200.0, 300.0, 50.0, 588.0],
            "笔数": [1, 2, 3, 4, 65],
        }
    )
    raw = d / "raw"
    raw.mkdir()
    df.to_parquet(raw / "raw_0.parquet", index=False)
    (raw / "manifest.json").write_text(
        json.dumps([{"index": 0, "name": "销售明细", "rows": 5,
                     "columns": list(df.columns)}], ensure_ascii=False),
        encoding="utf-8",
    )
    build_series_catalog(
        [RawTable(name="销售明细", df=df, source_kind="file", source_path="m.csv")], d
    )
    return d


@pytest.fixture
def state(session: Path) -> PlanSessionState:
    catalog = SeriesCatalog.from_manifest(str(session))
    return PlanSessionState(catalog=catalog, agent_logs=[])


@pytest.fixture
def ctx() -> ToolContext:
    return ToolContext(auto_confirm=True)


SQL_TOTAL = (
    "select 城市, sum(销售额) as 销售额 from table_0 "
    "where 城市 != '合计' group by 城市 order by 销售额 desc"
)


class TestDescribeDatasetTool:
    async def test_lists_raw_and_series(self, state, session, ctx):
        tool = DescribeDatasetTool(str(session))
        out = await tool.call({}, ctx)
        assert out.success
        assert "table_0" in out.output and "销售明细" in out.output
        assert "series_" in out.output

    async def test_uses_catalog_datasets_dir(self, state, ctx):
        tool = DescribeDatasetTool(state.catalog.datasets_dir)
        out = await tool.call({}, ctx)
        assert out.success


class TestRunViewTool:
    async def test_preview_only(self, state, ctx):
        tool = RunViewTool(state)
        before = len(state.catalog.series)
        out = await tool.call(
            RunViewInput(
                spec={"kind": "sql", "inputs": ["table_0"], "sql": SQL_TOTAL},
                mode="preview",
            ).model_dump(),
            ctx,
        )
        assert out.success
        assert "preview" in out.output
        assert len(state.catalog.series) == before, "preview 不注册系列"
        assert not (Path(state.catalog.datasets_dir) / "views").exists()

    async def test_materialize_registers_series_and_manifest(
        self, state, session: Path, ctx
    ):
        tool = RunViewTool(state)
        out = await tool.call(
            RunViewInput(
                spec={
                    "kind": "sql", "inputs": ["table_0"], "sql": SQL_TOTAL,
                    "title": "按城市合计",
                },
                mode="materialize",
            ).model_dump(),
            ctx,
        )
        assert out.success, out.error
        new_series = state.catalog.series[-1]
        assert "series_id" in out.output or "按城市合计" in out.output
        assert (session / "views").is_dir()
        manifest = json.loads((session / "manifest.json").read_text(encoding="utf-8"))
        ids = {s["series_id"] for s in manifest["series"]}
        assert new_series.series_id in ids, "manifest 已重写（磁盘与内存一致）"
        entry = next(s for s in manifest["series"] if s["series_id"] == new_series.series_id)
        assert entry["extra_semantics"]["origin"] == "view"
        assert entry["extra_semantics"]["view"]["spec_summary"].lower().startswith("select")
        assert new_series.source_table == "按城市合计"

    async def test_derived_series_passes_plan_validation(self, state, ctx):
        tool = RunViewTool(state)
        out = await tool.call(
            RunViewInput(
                spec={"kind": "sql", "inputs": ["table_0"], "sql": SQL_TOTAL,
                      "title": "按城市合计"},
                mode="materialize",
            ).model_dump(),
            ctx,
        )
        assert out.success
        series = state.catalog.series[-1]
        plan = {
            "plan_id": "p1", "plan_name": "城市排行", "chart_type": "Bar",
            "series_id": series.series_id,
            "data_interface": {"row_label": series.row_label_column,
                               "value_columns": series.column_label_columns},
        }
        assert validate_one_plan(plan, state.catalog, None, state.agent_logs)

    async def test_derived_series_loadable_with_df(self, state):
        tool = RunViewTool(state)
        out = await tool.call(
            RunViewInput(
                spec={"kind": "sql", "inputs": ["table_0"], "sql": SQL_TOTAL,
                      "title": "按城市合计"},
                mode="materialize",
            ).model_dump(),
            ctx,
        )
        assert out.success
        series = state.catalog.series[-1]
        df = pd.read_parquet(series.data_path)
        assert list(df.columns) == ["城市", "销售额"] or "销售额" in df.columns
        assert df["销售额"].sum() == 650.0  # 合计行 588 + 62 不混入

    async def test_rerun_same_spec_no_duplicate_series(self, state, ctx):
        tool = RunViewTool(state)
        spec = {
            "kind": "sql", "inputs": ["table_0"], "sql": SQL_TOTAL,
            "title": "按城市合计",
        }
        out1 = await tool.call(RunViewInput(spec=spec, mode="materialize").model_dump(), ctx)
        out2 = await tool.call(RunViewInput(spec=spec, mode="materialize").model_dump(), ctx)
        assert out1.success and out2.success
        view_ids = [
            (s.extra_semantics or {}).get("view", {}).get("view_id")
            for s in state.catalog.series
        ]
        assert len([v for v in view_ids if v]) == 1  # 只注册了一次
        assert "缓存命中" in out2.output

    async def test_bad_sql_structured_failure(self, state, ctx):
        tool = RunViewTool(state)
        out = await tool.call(
            RunViewInput(
                spec={"kind": "sql", "inputs": ["table_0"],
                      "sql": "update table_0 set 销售额 = 0"},
            ).model_dump(),
            ctx,
        )
        assert not out.success
        assert "WRITE_STATEMENT_REJECTED" in out.error

    async def test_unknown_alias_failure(self, state, ctx):
        tool = RunViewTool(state)
        out = await tool.call(
            RunViewInput(
                spec={"kind": "sql", "inputs": ["table_bomb"],
                      "sql": "select 1 from x order by 1"},
            ).model_dump(),
            ctx,
        )
        assert not out.success
        assert "INPUT_NOT_FOUND" in out.error


class TestRegisterViewSeries:
    async def test_title_empty_falls_back_to_summary(self, state, session: Path, ctx):
        """spec 不带 title 时系列名自动取视图摘要，不出现空名。"""
        tool = RunViewTool(state)
        out = await tool.call(
            RunViewInput(
                spec={
                    "kind": "sql", "inputs": ["table_0"],
                    "sql": "select 月份, sum(销售额) as 销售额 from table_0 "
                           "group by 月份 order by 月份",
                },
                mode="materialize",
            ).model_dump(),
            ctx,
        )
        assert out.success
        series = state.catalog.series[-1]
        assert series.series_id and series.name
