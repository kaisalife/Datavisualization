"""Series 数据形态摘要回归（无 LLM）。

规划阶段要按"时间点/类别数、指标数、是否含负值"选图表类型，
这些数字必须在 series 落盘时就写进 manifest，不能只留给模型猜。
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from service.data_ingestion.models import RawTable
from service.data_ingestion.series import build_series_catalog
from service.data_ingestion.series.models import SemanticSeries, SeriesCatalog
from service.data_ingestion.series.shape import (
    compute_series_shape,
    format_shape_summary,
    suggest_chart_types,
)

pytestmark = pytest.mark.whitebox


def _series(tmp_path: Path, df: pd.DataFrame, axis_kind: str, row: str,
            columns: list[str], series_id: str = "t.s") -> SemanticSeries:
    """把 DataFrame 落成 parquet，并带上与 splitter 相同的形态元数据。"""
    path = tmp_path / f"{series_id.replace('.', '_')}.parquet"
    df.to_parquet(path, index=False)
    shape = compute_series_shape(df, axis_kind, row, columns)
    return SemanticSeries(
        series_id=series_id,
        name=series_id,
        axis_kind=axis_kind,
        row_label_column=row,
        column_label_columns=columns,
        data_path=str(path),
        source_table="t",
        description="测试系列",
        extra_semantics={"shape": shape},
    )


def test_time_series_shape_counts_points_and_measures(tmp_path: Path):
    df = pd.DataFrame({
        "月份": [f"{m}月" for m in range(1, 13)],
        "销售额": [100 + m * 10 for m in range(12)],
        "利润": [10 + m for m in range(12)],
    })
    shape = compute_series_shape(df, "time_series", "月份", ["销售额", "利润"])

    assert shape["rows"] == 12
    assert shape["row_labels"] == 12
    assert shape["measure_count"] == 2
    assert shape["time_like"] is True
    assert shape["has_negative"] is False
    assert shape["row_label_kind"] == "time"
    assert shape["row_label_examples"][0] == "1月"
    assert "12 个时间点" in format_shape_summary(shape)


def test_categorical_shape_detects_negative_values(tmp_path: Path):
    df = pd.DataFrame({
        "城市": ["北京", "上海", "广州"],
        "销售额": [120, -20, 80],
    })
    shape = compute_series_shape(df, "categorical_comparison", "城市", ["销售额"])

    assert shape["row_labels"] == 3
    assert shape["has_negative"] is True
    assert shape["non_negative"] is False
    assert "含负值" in format_shape_summary(shape)


def test_suggest_chart_types_follows_data_shape():
    time_shape = {"row_labels": 12, "measure_count": 1, "time_like": True}
    rec, alt, reason = suggest_chart_types("time_series", time_shape)
    assert rec[0] == "Line"
    assert "Area" in rec
    assert "时间点" in reason

    cat_shape = {
        "row_labels": 4, "measure_count": 1, "non_negative": True,
        "time_like": False,
    }
    rec, alt, _ = suggest_chart_types("categorical_comparison", cat_shape)
    assert rec == ["Bar"]
    assert "Pie" in alt

    negative_shape = {
        "row_labels": 4, "measure_count": 1, "non_negative": False,
        "time_like": False,
    }
    rec, alt, _ = suggest_chart_types("categorical_comparison", negative_shape)
    assert rec == ["Bar"]
    assert "Pie" not in alt


def test_manifest_persists_shape(tmp_path: Path):
    df = pd.DataFrame({
        "月份": [f"{m}月" for m in range(1, 7)],
        "销售额": [100, 120, 150, 140, 180, 200],
    })
    catalog = build_series_catalog(
        [RawTable(name="sales", df=df, source_kind="file", source_path="sales.csv")],
        tmp_path,
    )

    assert catalog.series
    for series in catalog.series:
        shape = series.extra_semantics.get("shape")
        assert shape and shape["row_labels"] >= 1

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert "shape" in manifest["series"][0]["extra_semantics"]


def test_index_prompt_contains_shape_and_suggestion(tmp_path: Path):
    df = pd.DataFrame({
        "月份": [f"{m}月" for m in range(1, 7)],
        "销售额": [100, 120, 150, 140, 180, 200],
    })
    series = _series(tmp_path, df, "time_series", "月份", ["销售额"])
    catalog = SeriesCatalog(datasets_dir=str(tmp_path), series=[series])

    prompt = catalog.to_index_prompt()
    assert "6 个时间点" in prompt
    assert "建议 Line/Area" in prompt
