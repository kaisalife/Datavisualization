"""数值文本归一化回归：1,200 / 12.5% / (1,200) 等。"""
from __future__ import annotations

import math

import pandas as pd

from service.data_ingestion.normalize import coerce_numeric_columns


def test_thousands_percent_and_accounting_negative():
    df = pd.DataFrame(
        {
            "城市": ["北京", "上海"],
            "销售额": ["1,200", "1,300"],
            "增长率": ["12.5%", "13%"],
            "利润": ["(1,200)", "-300"],
        }
    )

    out = coerce_numeric_columns(df)

    assert out["销售额"].tolist() == [1200, 1300]
    assert out["增长率"].tolist() == [12.5, 13.0]
    assert out["利润"].tolist() == [-1200, -300]
    assert out["城市"].tolist() == ["北京", "上海"]


def test_identifier_columns_stay_text():
    df = pd.DataFrame(
        {
            "编号": ["001", "002"],
            "电话": ["13800138000", "13900139000"],
            "order_id": ["123", "456"],
            "width": ["123", "456"],
        }
    )

    out = coerce_numeric_columns(df)

    assert out["编号"].tolist() == ["001", "002"]
    assert out["电话"].tolist() == ["13800138000", "13900139000"]
    assert out["order_id"].tolist() == ["123", "456"]
    # width 只是名字里含 "id" 字符，不是 id 字段，应该正常转数值
    assert out["width"].tolist() == [123, 456]


def test_mixed_column_is_left_untouched():
    df = pd.DataFrame({"指标": ["A", "B"], "值": ["1,200", "约 300"]})

    out = coerce_numeric_columns(df)

    assert out["值"].tolist() == ["1,200", "约 300"]
    assert out["值"].dtype == object


def test_null_tokens_become_nan_when_rest_are_numeric():
    df = pd.DataFrame({"值": ["1,200", "—", "1,300", "暂无"]})

    out = coerce_numeric_columns(df)

    assert out["值"].tolist()[0] == 1200
    assert math.isnan(out["值"].tolist()[1])
    assert out["值"].tolist()[2] == 1300
    assert math.isnan(out["值"].tolist()[3])


def test_units_are_not_stripped():
    df = pd.DataFrame({"销售额": ["1,200 万元", "1,300 万元"]})

    out = coerce_numeric_columns(df)

    assert out["销售额"].tolist() == ["1,200 万元", "1,300 万元"]


def test_fullwidth_currency_spaces_and_european_format():
    df = pd.DataFrame(
        {
            "a": ["１，２００", "１，３００"],
            "b": ["¥1,200", "¥1,300"],
            "c": ["1 200", "1 300"],
            "d": ["1.234,56", "2.345,67"],
        }
    )

    out = coerce_numeric_columns(df)

    assert out["a"].tolist() == [1200, 1300]
    assert out["b"].tolist() == [1200, 1300]
    assert out["c"].tolist() == [1200, 1300]
    assert out["d"].tolist() == [1234.56, 2345.67]


def test_long_digits_without_separator_stay_text():
    df = pd.DataFrame({"序号": ["123456789012", "123456789013"]})

    out = coerce_numeric_columns(df)

    assert out["序号"].tolist() == ["123456789012", "123456789013"]


def test_already_numeric_frame_is_unchanged():
    df = pd.DataFrame({"城市": ["北京"], "销售额": [1200], "增长率": [12.5]})

    out = coerce_numeric_columns(df)

    pd.testing.assert_frame_equal(out, df)


async def test_ingest_coerces_numeric_text(tmp_path):
    """完整 ingest：CSV 里的 "1,200" 要变成数值列并参与指标识别。"""
    from service.data_ingestion import DataSource, ingest

    path = tmp_path / "sales.csv"
    path.write_text(
        '城市,销售额,增长率\n北京,"1,200",12.5%\n上海,"1,300",13%\n',
        encoding="utf-8",
    )

    profile = await ingest(DataSource(kind="file", path=str(path), name="sales"))

    schema = {c["name"]: c["type"] for c in profile.schema}
    assert "int" in schema["销售额"] or "float" in schema["销售额"]
    assert "float" in schema["增长率"]
    assert profile.column_semantics["销售额"] == "measure"
    assert profile.column_semantics["增长率"] == "measure"
    assert profile.preview[0]["销售额"] == 1200
