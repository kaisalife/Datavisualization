"""Series 拆分与列语义回归。

重点覆盖「时间词出现在指标名里」的场景：
``2023 年_销售额`` 是指标，不是时间点；``2020 年`` / ``order_date`` 才是时间列。
"""
from __future__ import annotations

import pandas as pd

from service.data_ingestion.profiler import _is_time_label
from service.data_ingestion.series.splitter import (
    _infer_semantics_for_df,
    _time_header_cols,
    split_raw_table,
)


def test_time_label_detection():
    assert _is_time_label("2023 年")
    assert _is_time_label("2023年")
    assert _is_time_label("1 月")
    assert _is_time_label("年份")
    assert _is_time_label("统计时间")
    assert _is_time_label("2023-01")
    assert _is_time_label("Q2")
    assert _is_time_label("order_date")
    assert _is_time_label("update_time")
    assert _is_time_label("sales_year")
    assert _is_time_label(2020)

    assert not _is_time_label("2023 年_销售额")
    assert not _is_time_label("销售额_2023")
    assert not _is_time_label("2023年销售额")
    assert not _is_time_label("year_sales")
    assert not _is_time_label("update")
    assert not _is_time_label("城市")


def test_metric_year_columns_are_measures_not_time():
    df = pd.DataFrame(
        {
            "城市": ["北京", "上海", "广州"],
            "2023 年_销售额": [1200, 1100, 900],
            "2023 年_利润": [300, 280, 210],
            "2024 年_销售额": [1500, 1400, 1250],
            "2024 年_利润": [400, 360, 300],
        }
    )

    semantics = _infer_semantics_for_df(df)

    assert semantics["城市"] == "dimension"
    metric_cols = list(df.columns[1:])
    assert all(semantics[c] == "measure" for c in metric_cols)

    specs = split_raw_table(df, "sales")

    assert len(specs) == 1
    assert specs[0]["axis_kind"] == "categorical_comparison"
    assert specs[0]["row_label_column"] == "城市"
    assert specs[0]["column_label_columns"] == metric_cols


def test_wide_table_with_year_headers_splits_per_indicator():
    df = pd.DataFrame(
        {
            "指标": ["GDP", "人口"],
            "2020 年": [100, 10],
            "2021 年": [110, 11],
            "2022 年": [120, 12],
        }
    )

    assert _time_header_cols(df) == ["2020 年", "2021 年", "2022 年"]

    specs = split_raw_table(df, "wide")

    assert len(specs) == 2
    assert all(spec["axis_kind"] == "time_series" for spec in specs)
    assert specs[0]["row_label_column"] == "时间"
    assert specs[0]["column_label_columns"] == ["值"]
    assert specs[0]["df"]["时间"].tolist() == ["2020 年", "2021 年", "2022 年"]
    assert specs[0]["df"]["值"].tolist() == [100, 110, 120]
    assert specs[0]["name"] == "GDP"
    assert specs[1]["name"] == "人口"


def test_bare_year_columns_are_time_headers():
    df = pd.DataFrame(
        {
            "指标": ["A", "B"],
            2020: [1, 2],
            2021: [3, 4],
            2022: [5, 6],
        }
    )

    assert _time_header_cols(df) == [2020, 2021, 2022]

    specs = split_raw_table(df, "wide")

    assert len(specs) == 2
    assert specs[0]["df"]["时间"].tolist() == ["2020", "2021", "2022"]


def test_time_column_with_measures_splits_per_measure():
    df = pd.DataFrame(
        {
            "年份": [2021, 2022, 2023],
            "销售额": [100, 120, 150],
            "利润": [10, 12, 15],
        }
    )

    semantics = _infer_semantics_for_df(df)
    assert semantics["年份"] == "time"
    assert semantics["销售额"] == "measure"

    specs = split_raw_table(df, "yearly")

    assert len(specs) == 2
    assert all(spec["axis_kind"] == "time_series" for spec in specs)
    assert {spec["row_label_column"] for spec in specs} == {"年份"}
    assert [spec["name"] for spec in specs] == ["销售额", "利润"]
