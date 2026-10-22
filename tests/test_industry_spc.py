"""过程稳定性 / SPC 场景回归（无 LLM）：X-MR 基准 + 接入形态 + 技能命中。

数据与验收基准见 tests/fixtures/industry/spc_stability/README.md；
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

FIXTURE_DIR = Path(__file__).resolve().parents[0] / "fixtures" / "industry" / "spc_stability"
CSV_PATH = FIXTURE_DIR / "coating_thickness.csv"

# README 基准（make_coating_spc_log.py 输出）
EXPECTED_CENTER = 20.0403
EXPECTED_MR_BAR = 0.0489
EXPECTED_SIGMA = 0.0434
EXPECTED_UCL = 20.1705
EXPECTED_LCL = 19.9102
EXPECTED_OUTLIERS = [20.18, 20.23, 20.20]


def _column(df: pd.DataFrame, keyword: str) -> str:
    for name in df.columns:
        if keyword in str(name):
            return str(name)
    raise AssertionError(f"缺少列: {keyword} in {list(df.columns)}")


@pytest.fixture(scope="module")
def raw_log() -> pd.DataFrame:
    return pd.read_csv(CSV_PATH, encoding="gbk")


def test_fixture_is_realistic(raw_log: pd.DataFrame):
    assert (FIXTURE_DIR / "README.md").is_file()
    assert (FIXTURE_DIR / "make_coating_spc_log.py").is_file()

    assert len(raw_log) == 30
    # 缺失值占位符保留原样（不插值）
    value_col = _column(raw_log, "面密度")
    assert "—" in raw_log[value_col].astype(str).tolist()
    # 恒定规格列（不能当指标画）
    assert raw_log[_column(raw_log, "规格上限")].nunique() == 1
    assert raw_log[_column(raw_log, "规格下限")].nunique() == 1


def test_xmr_baseline_matches_readme(raw_log: pd.DataFrame):
    value_col = _column(raw_log, "面密度")
    values = pd.to_numeric(raw_log[value_col], errors="coerce").dropna()

    center = float(values.mean())
    mr_bar = float(values.diff().abs().dropna().mean())
    sigma = mr_bar / 1.128
    ucl, lcl = center + 3 * sigma, center - 3 * sigma
    outliers = [round(float(v), 2) for v in values if v > ucl or v < lcl]

    assert round(center, 4) == EXPECTED_CENTER
    assert round(mr_bar, 4) == EXPECTED_MR_BAR
    assert round(sigma, 4) == EXPECTED_SIGMA
    assert round(ucl, 4) == EXPECTED_UCL
    assert round(lcl, 4) == EXPECTED_LCL
    assert outliers == EXPECTED_OUTLIERS
    # 控制限比规格限更早发现问题：超控制限但未超规格
    assert all(v <= 20.6 for v in outliers)


async def test_ingest_keeps_single_measure_series_not_operator_pivot():
    """操作员是属性列：不能被当成透视维度拆成 3 列稀疏宽表。"""
    profile = await ingest(DataSource(kind="file", path=str(CSV_PATH), name="极片涂布面密度"))

    series = list(profile.series_catalog.series)
    assert len(series) == 1, [(s.name, s.column_label_columns) for s in series]
    spec = series[0]
    columns = list(spec.column_label_columns or [])
    assert any("面密度" in c for c in columns)
    assert not any(name in columns for name in ("张伟", "李娜", "王强"))
    assert spec.extra_semantics.get("shape", {}).get("time_like") is True

    df = pd.read_parquet(spec.data_path)
    assert "记录时间" in df.columns
    assert len(df) == 30
    assert df[_column(df, "面密度")].isna().sum() == 1  # 缺失值保留为 NaN


def _series(rows: int, time_like: bool) -> SimpleNamespace:
    return SimpleNamespace(
        extra_semantics={"shape": {"rows": rows, "time_like": time_like}},
        axis_kind="time_series" if time_like else "generic",
        column_label_columns=[],
    )


def test_spc_skill_code_uses_is_scale_not_scale():
    """pyecharts 2.1：AxisOpts 的缩放参数是 is_scale，写 scale 会 TypeError。"""
    import re

    body = (Path(__file__).resolve().parents[1] / "skills" / "spc-stability" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    code_blocks = "\n".join(
        match.group(1) for match in re.finditer(r"```python(.*?)```", body, re.S)
    )
    assert "is_scale=True" in code_blocks
    assert "scale=True" not in code_blocks.replace("is_scale=True", "")


def test_spc_skill_is_keyword_gated_and_selected():
    registry = get_skill_registry()
    skill = registry.get("spc-stability")

    assert skill is not None
    assert skill.metadata.get("require_keywords") is True
    assert "Line" in (skill.metadata.get("chart_types") or [])

    common = dict(
        chart_type="Line",
        analysis_task="trend",
        time_like=True,
        rows=30,
        series_count=3,
    )
    assert skill.matches(
        user_prompt="涂布一线的极片面密度这一个月稳不稳定？有没有超出控制限的点", **common
    )
    # 普通趋势不命中
    assert not skill.matches(user_prompt="销售额月度趋势", **common)

    selected = registry.select(
        plan={"chart_type": "Line", "analysis_task": "trend"},
        series=_series(rows=30, time_like=True),
        user_prompt="面密度稳不稳定，有没有超出控制限的点",
    )
    assert [s.name for s in selected][:1] == ["spc-stability"]
