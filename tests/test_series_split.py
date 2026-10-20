"""Series 拆分与列语义回归。

重点覆盖「时间词出现在指标名里」的场景：
``2023 年_销售额`` 是指标，不是时间点；``2020 年`` / ``order_date`` 才是时间列。
"""
from __future__ import annotations

import pandas as pd

from service.data_ingestion.profiler import _is_time_label
from service.data_ingestion.series.splitter import (
    _infer_semantics_for_df,
    _natural_key,
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


def test_time_series_sorted_naturally():
    df = pd.DataFrame(
        {"月份": ["10月", "2月", "1月"], "销售额": [10, 20, 30]}
    )

    spec = split_raw_table(df, "time")[0]

    assert spec["axis_kind"] == "time_series"
    assert spec["df"]["月份"].tolist() == ["1月", "2月", "10月"]
    assert spec["df"]["销售额"].tolist() == [30, 20, 10]


def test_duplicate_time_points_are_aggregated():
    df = pd.DataFrame(
        {"月份": ["1月", "1月", "2月"], "销售额": [10, 20, 30]}
    )

    spec = split_raw_table(df, "time")[0]

    assert len(spec["df"]) == 2
    assert spec["df"]["销售额"].tolist() == [30, 30]


def test_duplicate_rate_time_points_use_mean():
    df = pd.DataFrame(
        {"月份": ["1月", "1月", "2月"], "增长率": [10.0, 20.0, 30.0]}
    )

    spec = split_raw_table(df, "time")[0]

    assert spec["df"]["增长率"].tolist() == [15.0, 30.0]


def test_wide_time_measures_are_sorted():
    df = pd.DataFrame(
        {
            "年份": [2023, 2021, 2022],
            "销售额": [300, 100, 200],
            "利润": [30, 10, 20],
        }
    )

    specs = split_raw_table(df, "wide")

    assert len(specs) == 2
    assert all(spec["df"]["年份"].tolist() == [2021, 2022, 2023] for spec in specs)


def test_long_table_pivots_dimension_over_time():
    df = pd.DataFrame(
        {
            "城市": ["北京", "北京", "北京", "上海", "上海", "上海"],
            "月份": ["1月", "2月", "3月", "1月", "2月", "3月"],
            "销售额": [100, 120, 140, 90, 95, 110],
        }
    )

    semantics = _infer_semantics_for_df(df)
    assert semantics["月份"] == "time"
    assert semantics["城市"] == "dimension"
    assert semantics["销售额"] == "measure"

    specs = split_raw_table(df, "long")

    assert len(specs) == 1
    spec = specs[0]
    assert spec["axis_kind"] == "time_series"
    assert spec["row_label_column"] == "月份"
    assert spec["column_label_columns"] == ["北京", "上海"]
    assert spec["name"] == "销售额 按城市"
    assert spec["df"]["月份"].tolist() == ["1月", "2月", "3月"]
    assert spec["df"]["北京"].tolist() == [100, 120, 140]
    assert spec["df"]["上海"].tolist() == [90, 95, 110]


def test_long_table_multiple_measures_make_one_series_each():
    df = pd.DataFrame(
        {
            "城市": ["北京", "北京", "上海", "上海"],
            "月份": ["1月", "2月", "1月", "2月"],
            "销售额": [100, 120, 90, 95],
            "利润": [10, 12, 9, 8],
        }
    )

    specs = split_raw_table(df, "long")

    assert len(specs) == 2
    assert [spec["name"] for spec in specs] == ["销售额 按城市", "利润 按城市"]
    assert all(spec["column_label_columns"] == ["北京", "上海"] for spec in specs)


def test_long_table_sorts_time_naturally():
    df = pd.DataFrame(
        {
            "城市": ["北京", "北京", "北京", "上海", "上海", "上海"],
            "月份": ["10月", "2月", "1月", "10月", "2月", "1月"],
            "销售额": [10, 20, 30, 40, 50, 60],
        }
    )

    spec = split_raw_table(df, "long")[0]
    ordered = spec["df"].sort_values("月份", key=lambda s: s.map(_natural_key))

    assert spec["df"]["月份"].tolist() == ["1月", "2月", "10月"]
    assert ordered["北京"].tolist() == [30, 20, 10]


def test_single_category_falls_back_to_simple_time_series():
    df = pd.DataFrame(
        {
            "城市": ["北京", "北京", "北京"],
            "月份": ["1月", "2月", "3月"],
            "销售额": [100, 120, 140],
        }
    )

    specs = split_raw_table(df, "single")

    assert len(specs) == 1
    assert specs[0]["row_label_column"] == "月份"
    assert specs[0]["column_label_columns"] == ["销售额"]


def test_multiple_dimensions_pick_smallest_cardinality():
    df = pd.DataFrame(
        {
            "省份": ["河北", "河北", "河北", "广东", "广东", "广东"],
            "城市": ["石家庄", "石家庄", "石家庄", "广州", "广州", "广州"],
            "月份": ["1月", "2月", "3月", "1月", "2月", "3月"],
            "销售额": [10, 20, 30, 40, 50, 60],
        }
    )

    spec = split_raw_table(df, "long")[0]

    assert spec["row_label_column"] == "月份"
    assert spec["column_label_columns"] == ["河北", "广东"]


def test_high_cardinality_dimension_aggregates_ranking():
    cities = [f"城市{i}" for i in range(1, 21)]
    rows = []
    for idx, city in enumerate(cities, start=1):
        rows.append({"城市": city, "月份": "1月", "销售额": idx * 10})
        rows.append({"城市": city, "月份": "2月", "销售额": idx * 5})
    df = pd.DataFrame(rows)

    specs = split_raw_table(df, "ranking")

    assert len(specs) == 1
    spec = specs[0]
    assert spec["axis_kind"] == "categorical_comparison"
    assert spec["row_label_column"] == "城市"
    assert spec["column_label_columns"] == ["销售额"]
    assert len(spec["df"]) == 20
    # 城市20：(20*10 + 20*5) = 300，排第一
    assert spec["df"].iloc[0]["城市"] == "城市20"
    assert spec["df"].iloc[0]["销售额"] == 300


def test_duplicate_cells_use_sum_or_mean_by_measure_name():
    df = pd.DataFrame(
        {
            "城市": ["北京", "北京", "上海", "上海"],
            "月份": ["1月", "1月", "1月", "1月"],
            "销售额": [10, 20, 30, 40],
            "增长率": [10.0, 20.0, 30.0, 40.0],
        }
    )

    specs = split_raw_table(df, "dup")
    by_name = {spec["name"]: spec for spec in specs}

    assert by_name["销售额 按城市"]["df"]["北京"].tolist() == [30]
    assert by_name["增长率 按城市"]["df"]["北京"].tolist() == [15.0]

