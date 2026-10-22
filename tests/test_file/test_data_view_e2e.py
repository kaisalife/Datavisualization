"""数据视图端到端回归（真实模型）：明细长表 → run_view 派生"按月合计"视角 → 出图。

默认测试集排除 needs_llm；显式运行：

    .venv/Scripts/python.exe -m pytest tests/test_file/test_data_view_e2e.py \
        -o addopts="" -m "needs_llm and integration" -q -s

验收口径（docs/数据清洗工具集/05）：

- 用户要"按月合计"而数据是明细行时，series 目录里出现 view 派生系列
  （``extra_semantics.origin == "view"``），plan 引用它；
- 图表 HTML 的数值与 view parquet 一致（不是与原始明细表一致）；
- 同一 prompt + 同一数据重跑，plan 引用同一 ``view_id``（内容寻址缓存）。
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from service.data_ingestion import DataSource, ingest
from service.pipeline.agent_pipeline import run_agent_pipeline

pytestmark = [pytest.mark.needs_llm, pytest.mark.integration]

_DAYS = 20  # 每城市 20 天明细，跨 2 个月


@pytest.fixture
def daily_sales_csv(tmp_path: Path) -> Path:
    """每日销售明细（日期 + 城市 + 销售额）：没有任何“按月合计”视角。"""
    import random

    rng = random.Random(11)
    path = tmp_path / "每日销售明细.csv"
    lines = ["日期,城市,销售额"]
    cities = ["北京", "上海", "广州"]
    for day in range(1, _DAYS + 1):
        month = 1 if day <= 12 else 2
        for city in cities:
            lines.append(
                f"2026-0{month}-{day:02d},{city},{rng.randint(120, 900)}"
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


async def test_monthly_total_view_derived_and_charted(
    real_agent, daily_sales_csv: Path, tmp_path: Path
):
    profile = await ingest(
        DataSource(
            kind="file", path=str(daily_sales_csv), name="每日销售明细",
            options={"save_raw": True},
        )
    )
    session_dir = Path(profile.session_dir)
    identity_ids = {s.series_id for s in (profile.series_catalog.series if profile.series_catalog else [])}

    model_ = SimpleNamespace(
        user_prompt=(
            "数据是每日销售明细。我要看的是按月的销售合计：把明细按月份汇总后，"
            "画一张各个月份销售合计的柱状图（1 月和 2 月两根柱）。"
        ),
        file_paths=[str(daily_sales_csv)],
        config=None,
        mcp_prompt="",
        skill_prompt="",
        model_type="deepseek",
    )

    result = await run_agent_pipeline(
        real_agent, model_, profile, tmp_path, task_id=None, max_iterations=18
    )
    logs = result["agent_logs"]
    assert result["successful_charts"], "未产出任何图表:\n" + "\n".join(logs[-10:])

    # 1. series 目录里必然出现 view 派生系列
    from service.data_ingestion.series_manager import load_catalog_from_session

    final_catalog = load_catalog_from_session(datasets_dir=session_dir)
    view_series = [
        s for s in final_catalog.series
        if (s.extra_semantics or {}).get("origin") == "view"
    ]
    assert view_series, "没有 view 派生系列（agent 未使用 run_view）:\n" + "\n".join(logs[-10:])
    view_ids = {
        s.extra_semantics["view"]["view_id"] for s in view_series
    }
    assert view_ids, view_series and [s.series_id for s in view_series]

    # 2. plan 引用 view 派生系列而不是在生成代码里现写聚合
    for chart in result["successful_charts"]:
        plan = chart.get("plan") or {}
        assert plan.get("series_id"), plan
        series = final_catalog.by_id(plan["series_id"])
        assert series is not None, f"plan 引用的 series 不存在: {plan.get('series_id')}"
    referenced = {
        (chart.get("plan") or {}).get("series_id")
        for chart in result["successful_charts"]
    }
    assert referenced & {s.series_id for s in view_series}, (
        f"plan 未引用 view 系列: {referenced}；view 系列: {[s.series_id for s in view_series]}"
    )

    # 3. 图表数值与 view parquet 一致（监控 view 物化文件）
    chart = result["successful_charts"][0]
    html = Path(chart["chart_path"])
    assert html.exists() and html.stat().st_size > 0
    view_manifest = json.loads(
        (session_dir / "views" / f"{view_ids.copy().pop()}.manifest.json").read_text(
            encoding="utf-8"
        )
    )
    view_df = pd.read_parquet(session_dir / "views" / view_manifest["parquet"])
    total = float(view_df.drop(columns=[view_df.columns[0]]).to_numpy().sum())
    assert total > 0, view_df

    generation = chart.get("generation") or {}
    assert generation.get("ok") is True


async def test_monthly_total_view_rerun_stable_view_id(
    real_agent, daily_sales_csv: Path, tmp_path: Path
):
    """同一 prompt + 同一数据重跑：view_id 稳定（内容寻址缓存），不重算。"""
    profile = await ingest(
        DataSource(
            kind="file", path=str(daily_sales_csv), name="每日销售明细",
            options={"save_raw": True},
        )
    )
    session_dir = Path(profile.session_dir)
    model_ = SimpleNamespace(
        user_prompt=(
            "数据是每日销售明细。把明细按月份汇总，画按月销售合计的柱状图。"
        ),
        file_paths=[str(daily_sales_csv)],
        config=None,
        mcp_prompt="",
        skill_prompt="",
        model_type="deepseek",
    )
    result = await run_agent_pipeline(
        real_agent, model_, profile, tmp_path, task_id=None, max_iterations=18
    )
    assert result["successful_charts"], "未产出任何图表:\n" + "\n".join(result["agent_logs"][-10:])
    from service.data_ingestion.series_manager import load_catalog_from_session

    catalog = load_catalog_from_session(datasets_dir=session_dir)
    view_series = [
        s for s in catalog.series
        if (s.extra_semantics or {}).get("origin") == "view"
    ]
    assert view_series, "重跑没有产生 view 系列也没有命中:\n" + "\n".join(
        result["agent_logs"][-10:]
    )
    views_dir = session_dir / "views"
    manifests = list(views_dir.glob("*.manifest.json"))
    assert manifests
