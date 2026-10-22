"""帕累托场景用例回归（无 LLM）：fixture 数据特征 + 接入层 shape + 加工范式基准。

数据与验收基准见 tests/fixtures/industry/pareto_quality/README.md；
真模型 e2e 在 tests/test_file/test_industry_e2e.py（needs_llm）。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from service.data_ingestion import DataSource, ingest
from service.skills import get_skill_registry

pytestmark = pytest.mark.whitebox

FIXTURE_DIR = Path(__file__).resolve().parents[0] / "fixtures" / "industry" / "pareto_quality"
CSV_PATH = FIXTURE_DIR / "defect_log.csv"

# README 基准（make_defect_log.py 输出）
EXPECTED_TOTAL = 102
EXPECTED_TOP = "焊点虚焊"
EXPECTED_TOP2_SHARE = 52.94


@pytest.fixture(scope="module")
def raw_log() -> pd.DataFrame:
    return pd.read_csv(CSV_PATH, encoding="gbk")


def test_fixture_files_present_and_realistic(raw_log: pd.DataFrame):
    assert (FIXTURE_DIR / "README.md").is_file()
    assert (FIXTURE_DIR / "make_defect_log.py").is_file()

    # 事件粒度 + 行业原生列名 + GBK
    assert list(raw_log.columns) == ["发生日期", "不良描述", "判定数量", "批次号", "备注"]
    assert len(raw_log) == 51
    assert raw_log["判定数量"].sum() == EXPECTED_TOTAL
    assert "表面划伤" in set(raw_log["不良描述"])  # 同义类目保留
    assert (raw_log["备注"] == "—").any()  # 占位符


def test_business_aggregation_baseline(raw_log: pd.DataFrame):
    agg = (
        raw_log.groupby("不良描述", as_index=False)["判定数量"].sum()
        .sort_values("判定数量", ascending=False, ignore_index=True)
    )
    assert agg.loc[0, "不良描述"] == EXPECTED_TOP
    assert agg.loc[0, "判定数量"] == 33

    cumulative = agg["判定数量"].cumsum() / EXPECTED_TOTAL * 100
    assert round(cumulative.iloc[1], 2) == EXPECTED_TOP2_SHARE
    assert round(cumulative.iloc[-1], 2) == 100.0
    # 长尾形态成立：前 2 项占比过半（帕累托才有信息量）
    assert cumulative.iloc[1] <= 80


async def test_ingest_produces_wide_series_with_defect_columns(tmp_path: Path):
    """接入层把事件日志拆成 时间×不良描述 宽表 series（生成代码拿到的形态）。"""
    profile = await ingest(
        DataSource(kind="file", path=str(CSV_PATH), name="SMT不良判定记录")
    )
    series_list = list(profile.series_catalog.series)
    assert series_list, "事件日志应至少拆出一条 series"

    wide = next(
        (s for s in series_list if len(s.column_label_columns or []) >= 5),
        None,
    )
    assert wide is not None, [
        (s.name, getattr(s, "column_label_columns", None)) for s in series_list
    ]
    assert bool(wide.extra_semantics.get("shape", {}).get("time_like")) or \
        wide.axis_kind == "time_series"

    # 宽表列向求和 == README 基准（这就是技能范式一的处理对象）
    df = pd.read_parquet(wide.data_path)
    numeric = [c for c in df.columns if c != wide.row_label_column]
    totals = df[numeric].sum(axis=0)
    assert int(totals.max()) == 33  # 焊点虚焊
    assert int(totals.sum()) == EXPECTED_TOTAL


def test_pareto_skill_is_keyword_gated():
    """require_keywords 门控：普通排行不命中，业务话术命中（详细单测在 test_skill_registry）。"""
    skill = get_skill_registry().get("pareto-quality")
    assert skill is not None
    assert skill.metadata.get("require_keywords")
