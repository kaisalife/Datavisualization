"""数据视图插件端到端回归（真实模型）：分钟线 → ohlc_resample → 周线 Candlestick。

默认测试集排除 needs_llm；显式运行：

    .venv/Scripts/python.exe -m pytest tests/test_file/test_data_view_plugin_e2e.py \
        -o addopts="" -m "needs_llm and integration" -q -s

验收口径（docs/数据清洗工具集/05 P2）：

- 明细是分钟级 OHLC，用户要周线 K：规划 agent 应通过 data-view-usage /
  financial-candlestick 技能发现 ohlc_resample 插件，run_view(kind=plugin) 造出
  周线系列，plan 引用它而不是在生成代码里现写分组聚合；
- 插件的 plugin_version 参与内容寻址：manifest 里能对上 describe_dataset
  给出的版本。
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from service.data_ingestion import DataSource, ingest
from service.pipeline.agent_pipeline import run_agent_pipeline

pytestmark = [pytest.mark.needs_llm, pytest.mark.integration]


@pytest.fixture
def minute_ohlc_csv(tmp_path: Path) -> Path:
    """5 天 × 每天多根分钟 K 的 OHLC 明细（没有现成周线视角）。"""
    import random

    rng = random.Random(23)
    path = tmp_path / "分钟OHLC.csv"
    lines = ["时间,开盘,最高,最低,收盘,成交量"]
    price = 100.0
    base_day = "2026-01-05"
    for day_index, day in enumerate(["05", "06", "07", "08", "09"]):
        for minute in range(0, 45, 15):
            open_price = round(price, 2)
            close_price = round(price + rng.uniform(-4, 4), 2)
            high_price = round(max(open_price, close_price) + rng.uniform(0, 2), 2)
            low_price = round(min(open_price, close_price) - rng.uniform(0, 2), 2)
            volume = rng.randint(1000, 9000)
            lines.append(
                f"{base_day[:8]}{day} 09:{minute:02d}:00,"
                f"{open_price},{high_price},{low_price},{close_price},{volume}"
            )
            price = close_price
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


async def test_weekly_candlestick_via_ohlc_resample(
    real_agent, minute_ohlc_csv: Path, tmp_path: Path
):
    profile = await ingest(
        DataSource(
            kind="file", path=str(minute_ohlc_csv), name="分钟OHLC",
            options={"save_raw": True},
        )
    )
    session_dir = Path(profile.session_dir)
    model_ = SimpleNamespace(
        user_prompt=(
            "这是分钟级 K 线行情（OpenAPI high low close 列是 开盘/最高/最低/收盘）。"
            "请先重采样成周线 K 线，然后画 2026 年 1 月的周线 Candlestick 蜡烛图。"
        ),
        file_paths=[str(minute_ohlc_csv)],
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

    from service.data_ingestion.series_manager import load_catalog_from_session
    from service.data_view.registry import get_default_registry

    catalog = load_catalog_from_session(datasets_dir=session_dir)
    view_series = [
        s for s in catalog.series
        if (s.extra_semantics or {}).get("origin") == "view"
    ]
    assert view_series, "没有 view 派生系列（agent 未使用 run_view）:\n" + "\n".join(logs[-10:])
    plugin_views = [
        s for s in view_series
        if (s.extra_semantics or {}).get("view", {}).get("kind") == "plugin"
    ]
    registered = get_default_registry().describe()
    outlined = {
        s.extra_semantics["view"]["spec_summary"].split("(", 1)[0]
        for s in plugin_views
    }
    assert "ohlc_resample" in outlined or "ts_bucket" in outlined, (
        f"插件视图缺失: {outlined}；已注册插件: {registered}"
    )
    # plugin_version 参与内容寻址：spec 摘要里的版本必须与注册表一致
    for s in plugin_views:
        summary = s.extra_semantics["view"]["spec_summary"]
        assert "ohlc_resample({" in summary or "ts_bucket({" in summary

    referenced = {
        (chart.get("plan") or {}).get("series_id")
        for chart in result["successful_charts"]
    }
    assert referenced & {s.series_id for s in view_series}, (
        f"plan 未引用 view 系列: {referenced}；view 系列: {[s.series_id for s in view_series]}"
    )
    chart = result["successful_charts"][0]
    assert (chart.get("generation") or {}).get("ok") is True
