"""KPI 仪表盘场景回归（无 LLM）：fixture 口径 + 接入形态 + 技能命中。

数据与验收基准见 tests/fixtures/industry/gauge_kpi/README.md；
真模型 e2e 在 tests/test_file/test_industry_e2e.py（needs_llm）。
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from service.data_ingestion import DataSource, ingest
from service.skills import get_skill_registry

pytestmark = pytest.mark.whitebox

FIXTURE_DIR = Path(__file__).resolve().parents[0] / "fixtures" / "industry" / "gauge_kpi"
CSV_PATH = FIXTURE_DIR / "wind_kpi_log.csv"


def _column(df: pd.DataFrame, keyword: str) -> str:
    for name in df.columns:
        if keyword in str(name):
            return str(name)
    raise AssertionError(f"缺少列: {keyword} in {list(df.columns)}")


@pytest.fixture(scope="module")
def raw_kpi() -> pd.DataFrame:
    return pd.read_csv(CSV_PATH, encoding="gbk")


def test_fixture_is_realistic_and_baseline_matches(raw_kpi: pd.DataFrame):
    assert (FIXTURE_DIR / "README.md").is_file()
    assert (FIXTURE_DIR / "make_wind_kpi_log.py").is_file()

    assert len(raw_kpi) == 8
    assert raw_kpi[_column(raw_kpi, "机组编号")].nunique() == 8
    # 千分位在引号里，读出来仍是文本；完成率需要自己换算
    actual_col = _column(raw_kpi, "本月发电")
    assert raw_kpi[actual_col].dtype == object
    assert "1,986" in str(raw_kpi.iloc[0][actual_col])

    actual = raw_kpi[actual_col].astype(str).str.replace(",", "", regex=False).astype(float)
    target = pd.to_numeric(raw_kpi[_column(raw_kpi, "目标发电")], errors="coerce")
    rate = (actual / target * 100).round(1)

    # README 基准：03 机组 = 1824 / 1900 = 96.0%
    assert rate.tolist() == [99.3, 102.1, 96.0, 101.6, 95.8, 98.0, 103.9, 106.9]
    unit = raw_kpi[_column(raw_kpi, "机组编号")].astype(str).str.zfill(2)
    assert rate[unit == "03"].iloc[0] == 96.0


async def test_ingest_keeps_single_generic_table():
    """8 台机组仍是一条 generic series（Gauge 依赖"单对象单指标"口径由代码过滤）。"""
    profile = await ingest(DataSource(kind="file", path=str(CSV_PATH), name="风电场月度考核"))

    assert profile.row_count == 8
    series = list(profile.series_catalog.series)
    assert len(series) == 1
    df = pd.read_parquet(series[0].data_path)
    assert "机组编号" in df.columns
    assert any("本月发电" in c for c in df.columns)
    assert any("目标发电" in c for c in df.columns)


def _series(rows: int, time_like: bool) -> SimpleNamespace:
    return SimpleNamespace(
        extra_semantics={"shape": {"rows": rows, "time_like": time_like}},
        axis_kind="time_series" if time_like else "generic",
        column_label_columns=[],
    )


def test_gauge_skill_is_keyword_gated_and_selected():
    registry = get_skill_registry()
    skill = registry.get("gauge-kpi-snapshot")

    assert skill is not None
    assert skill.metadata.get("require_keywords") is True
    assert "Gauge" in (skill.metadata.get("chart_types") or [])

    common = dict(
        chart_type="Gauge",
        analysis_task="comparison",
        time_like=False,
        rows=8,
        series_count=0,
    )
    # 业务话术命中（完成率/达标）
    assert skill.matches(user_prompt="3 号机组这个月发电量完成率怎么样，有没有达标", **common)
    # 普通排行不命中（没有场景词）
    assert not skill.matches(user_prompt="各城市销售额排行", **common)

    selected = registry.select(
        plan={"chart_type": "Gauge", "analysis_task": "comparison"},
        series=_series(rows=8, time_like=False),
        user_prompt="3 号机组这个月发电量完成率怎么样，有没有达标",
    )
    assert [s.name for s in selected][:1] == ["gauge-kpi-snapshot"]
