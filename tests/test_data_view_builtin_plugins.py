"""内置插件回归：ohlc_resample / ts_bucket 的聚合语义、错误与确定性。"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from service.data_view import DataViewError, ViewSpec
from service.data_view.engine import DataViewEngine
from service.data_view.registry import PluginRegistry


@pytest.fixture
def registry() -> PluginRegistry:
    """真实扫盘（plugins/data_view/ 下的插件是仓库文件，只读）。"""
    r = PluginRegistry()
    described = r.scan()
    assert described.get("ohlc_resample") and described.get("ts_bucket")
    return r


@pytest.fixture
def engine(registry: PluginRegistry) -> DataViewEngine:
    return DataViewEngine(registry=registry, max_rows=1000)


@pytest.fixture
def daily_ohlc() -> pd.DataFrame:
    """两周日线行情（W02: 01-05..09 + W03: 01-12/13/16），行序故意乱。"""
    rows = [
        ("2026-01-05", 104.0, 111.0, 100.0, 102.0, 13000),
        ("2026-01-06", 105.0, 112.0, 101.0, 108.0, 15000),
        ("2026-01-09", 116.0, 122.0, 114.0, 121.0, 17000),
        ("2026-01-08", 118.0, 121.0, 115.0, 116.0, 14000),
        ("2026-01-13", 124.0, 126.0, 122.0, 123.0, 12000),
        ("2026-01-07", 108.0, 120.0, 107.0, 118.0, 16000),
        ("2026-01-12", 120.0, 125.0, 119.0, 124.0, 11000),
        ("2026-01-16", 123.0, 130.0, 121.0, 128.0, 18000),
    ]
    return pd.DataFrame(
        rows,
        columns=["日期", "开盘", "最高", "最低", "收盘", "成交量"],
    )


def _run(engine: DataViewEngine, frame: pd.DataFrame, params: dict) -> pd.DataFrame:
    spec = ViewSpec(
        kind="plugin", plugin="ohlc_resample", plugin_version=1,
        params=params, inputs=["table_0"], title="重采样",
    )
    result = engine.execute(spec, {"table_0": frame}, mode="preview")
    return result.data


class TestOhlcResample:
    def test_weekly_first_max_min_last(self, engine: DataViewEngine, daily_ohlc: pd.DataFrame):
        out = _run(engine, daily_ohlc, {
            "time_column": "日期", "freq": "W",
            "open": "开盘", "high": "最高", "low": "最低", "close": "收盘",
            "volume": "成交量",
        })
        # 两周（W02 + W03，分组后各一条）
        assert len(out) == 2
        first, second = out.iloc[0], out.iloc[1]
        assert first["开盘"] == 104.0, "桶内 first 取时间最早的行"
        assert first["最高"] == 122.0 and first["最低"] == 100.0
        assert first["收盘"] == 121.0
        assert first["成交量"] == 13000 + 15000 + 16000 + 14000 + 17000
        assert second["开盘"] == 120.0 and second["收盘"] == 128.0
        assert second["最高"] == 130.0
        assert list(out.columns) == ["日期", "开盘", "最高", "最低", "收盘", "成交量"]

    def test_monthly_bucket_label(self, engine: DataViewEngine, daily_ohlc: pd.DataFrame):
        out = _run(engine, daily_ohlc, {
            "time_column": "日期", "freq": "M",
            "open": "开盘", "high": "最高", "low": "最低", "close": "收盘",
        })
        assert len(out) == 1
        assert out.iloc[0]["日期"] == "2026-01"
        assert "成交量" not in out.columns

    def test_out_of_order_input_same_result(self, engine: DataViewEngine, daily_ohlc: pd.DataFrame):
        params = {
            "time_column": "日期", "freq": "W",
            "open": "开盘", "high": "最高", "low": "最低", "close": "收盘",
        }
        out1 = _run(engine, daily_ohlc, params)
        out2 = _run(engine, daily_ohlc.sample(frac=1, random_state=7), params)
        pd.testing.assert_frame_equal(out1, out2), "行序打乱不改结果"

    def test_missing_column_rejected(self, engine: DataViewEngine, daily_ohlc: pd.DataFrame):
        with pytest.raises(DataViewError) as e:
            _run(engine, daily_ohlc, {
                "time_column": "date", "freq": "W",
                "open": "开盘", "high": "最高", "low": "最低", "close": "收盘",
            })
        assert e.value.code == "EXEC_ERROR"
        assert "缺少列" in str(e.value)

    def test_missing_param_rejected(self, engine: DataViewEngine, daily_ohlc: pd.DataFrame):
        with pytest.raises(DataViewError):
            _run(engine, daily_ohlc, {
                "freq": "W",
                "open": "开盘", "high": "最高", "low": "最低", "close": "收盘",
            })

    def test_bad_freq_rejected(self, engine: DataViewEngine, daily_ohlc: pd.DataFrame):
        with pytest.raises(DataViewError) as e:
            _run(engine, daily_ohlc, {
                "time_column": "日期", "freq": "3H",
                "open": "开盘", "high": "最高", "low": "最低", "close": "收盘",
            })
        assert "freq" in str(e.value)

    def test_empty_time_rejected(self, engine: DataViewEngine):
        frame = pd.DataFrame({
            "日期": ["坏值", ""], "开盘": [1.0, 2.0], "最高": [2.0, 3.0],
            "最低": [0.5, 1.0], "收盘": [1.5, 2.5],
        })
        with pytest.raises(DataViewError):
            _run(engine, frame, {
                "time_column": "日期", "freq": "D",
                "open": "开盘", "high": "最高", "low": "最低", "close": "收盘",
            })


@pytest.fixture
def highfreq() -> pd.DataFrame:
    """秒级采样：两个 1min 桶各 2 行，桶 2 含一个 None 温度。"""
    rows = [
        ("2026-01-05 10:00:00", 21.5, 1.1),
        ("2026-01-05 10:00:30", 22.0, 1.0),
        ("2026-01-05 10:01:30", None, 1.3),
        ("2026-01-05 10:01:50", 23.0, 1.6),
    ]
    return pd.DataFrame(rows, columns=["时间", "温度", "电流"])


class TestTsBucket:
    def test_minute_mean_and_max(self, engine: DataViewEngine, highfreq: pd.DataFrame):
        spec = ViewSpec(
            kind="plugin", plugin="ts_bucket", plugin_version=1,
            params={"time_column": "时间", "bucket": "1min",
                    "metrics": {"温度": "mean", "电流": "max"}},
            inputs=["table_0"], title="每分钟",
        )
        out = engine.execute(spec, {"table_0": highfreq}, mode="preview").data
        assert len(out) == 2
        assert list(out.columns) == ["时间", "温度", "电流"]
        # 桶1: 21.5/22.0 → mean 21.75；电流 1.1/1.0 → max 1.1
        assert out.iloc[0]["温度"] == pytest.approx(21.75)
        assert out.iloc[0]["电流"] == pytest.approx(1.1)
        # 桶2: None 跳过 → mean 23.0；电流 1.3/1.6 → max 1.6
        assert out.iloc[1]["温度"] == pytest.approx(23.0)
        assert out.iloc[1]["电流"] == pytest.approx(1.6)

    def test_count_counts_numeric_only(self, engine: DataViewEngine, highfreq: pd.DataFrame):
        spec = ViewSpec(
            kind="plugin", plugin="ts_bucket", plugin_version=1,
            params={"time_column": "时间", "bucket": "1min", "metrics": {"温度": "count"}},
            inputs=["table_0"], title="计数",
        )
        out = engine.execute(spec, {"table_0": highfreq}, mode="preview").data
        assert out.iloc[0]["温度"] == 2   # 21.5 / 22.0
        assert out.iloc[1]["温度"] == 1   # None 不计入，只有 23.0

    def test_deterministic_for_shuffled_input(self, engine: DataViewEngine, highfreq: pd.DataFrame):
        spec_params = {"time_column": "时间", "bucket": "1min",
                       "metrics": {"温度": "mean", "电流": "max"}}
        spec = ViewSpec(
            kind="plugin", plugin="ts_bucket", plugin_version=1,
            params=spec_params, inputs=["table_0"], title="每分钟",
        )
        out1 = engine.execute(spec, {"table_0": highfreq}, mode="preview").data
        out2 = engine.execute(
            spec, {"table_0": highfreq.sample(frac=1, random_state=3)}, mode="preview"
        ).data
        pd.testing.assert_frame_equal(out1, out2)

    def test_view_id_differs_from_ohlc(self, engine: DataViewEngine, daily_ohlc: pd.DataFrame):
        """同数据不同 spec → 不同 view_id（内容寻址、防缓存串键）。"""
        spec_a = ViewSpec(
            kind="plugin", plugin="ts_bucket", plugin_version=1,
            params={"time_column": "日期", "bucket": "1D", "metrics": {"开盘": "mean"}},
            inputs=["table_0"], title="日均",
        )
        spec_b = ViewSpec(
            kind="plugin", plugin="ts_bucket", plugin_version=1,
            params={"time_column": "日期", "bucket": "1D", "metrics": {"收盘": "mean"}},
            inputs=["table_0"], title="日均",
        )
        id_a = engine.execute(spec_a, {"table_0": daily_ohlc}, mode="preview").view_id
        id_b = engine.execute(spec_b, {"table_0": daily_ohlc}, mode="preview").view_id
        assert id_a != id_b

    def test_bad_bucket_rejected(self, engine: DataViewEngine, highfreq: pd.DataFrame):
        spec = ViewSpec(
            kind="plugin", plugin="ts_bucket", plugin_version=1,
            params={"time_column": "时间", "bucket": "weekly", "metrics": {"温度": "mean"}},
            inputs=["table_0"], title="周",
        )
        with pytest.raises(DataViewError) as e:
            engine.execute(spec, {"table_0": highfreq}, mode="preview")
        assert e.value.code == "EXEC_ERROR"

    def test_unknown_agg_rejected(self, engine: DataViewEngine, highfreq: pd.DataFrame):
        spec = ViewSpec(
            kind="plugin", plugin="ts_bucket", plugin_version=1,
            params={"time_column": "时间", "bucket": "1min", "metrics": {"温度": "stdev"}},
            inputs=["table_0"], title="标准差",
        )
        with pytest.raises(DataViewError):
            engine.execute(spec, {"table_0": highfreq}, mode="preview")

    def test_unknown_plugin_rejected(self, engine: DataViewEngine, highfreq: pd.DataFrame):
        spec = ViewSpec(
            kind="plugin", plugin="不存在的插件", plugin_version=1,
            params={}, inputs=["table_0"], title="x",
        )
        with pytest.raises(DataViewError):
            engine.execute(spec, {"table_0": highfreq}, mode="preview")


class TestMaterializeThroughPlugin:
    def test_materialize_writes_parquet(self, engine: DataViewEngine, daily_ohlc: pd.DataFrame,
                                        tmp_path: Path):
        session_dir = tmp_path / "ds_abcdef012345"
        session_dir.mkdir()
        spec = ViewSpec(
            kind="plugin", plugin="ohlc_resample", plugin_version=1,
            params={"time_column": "日期", "freq": "W",
                    "open": "开盘", "high": "最高", "low": "最低", "close": "收盘",
                    "volume": "成交量"},
            inputs=["table_0"], title="周线",
        )
        result = engine.execute(spec, {"table_0": daily_ohlc}, mode="materialize",
                                datasets_dir=str(session_dir))
        parquet = Path(result.extra["parquet_path"])
        assert parquet.is_file()
        loaded = pd.read_parquet(parquet)
        assert len(loaded) == 2
