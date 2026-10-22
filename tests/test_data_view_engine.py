"""执行器：SQL 聚合/透视/Top-N、错误码、行数上限、插件执行。"""
from __future__ import annotations

import pandas as pd
import pytest

from service.data_view import (
    DataViewError,
    DataViewEngine,
    PluginEntry,
    PluginRegistry,
    ViewSpec,
    spec_hash,
    view_id,
)
from service.data_view import (
    EMPTY_RESULT,
    INPUT_INVALID,
    EXEC_ERROR,
    PLUGIN_NOT_FOUND,
    ROW_LIMIT_EXCEEDED,
    SCHEMA_MISMATCH,
    SPEC_INVALID,
    UNORDERED_OUTPUT,
    WRITE_STATEMENT_REJECTED,
)


@pytest.fixture
def long_table() -> pd.DataFrame:
    """明细长表：城市 × 月份 × 销售额（含重复时间点与合计行）。"""
    return pd.DataFrame(
        {
            "城市": ["北京", "北京", "上海", "上海", "合计", "深圳"],
            "月份": ["1 月", "1 月", "2 月", "2 月", "3 月", "3 月"],
            "销售额": [100.0, 200.0, 300.0, 50.0, 9999.0, 20.0],
        }
    )


@pytest.fixture
def engine() -> DataViewEngine:
    return DataViewEngine()


SQL_BY_CITY = (
    "select 城市, sum(销售额) as 销售额 from table_0 "
    "where 城市 != '合计' group by 城市 order by 销售额 desc"
)


class TestSqlExecution:
    def test_groupby_topn_deterministic(self, engine, long_table):
        """聚合 + 排序：同 spec 同数据 → 同结果、同 view_id。"""
        spec = ViewSpec(kind="sql", sql=SQL_BY_CITY, inputs=["table_0"])
        r1 = engine.execute(spec, {"table_0": long_table})
        r2 = engine.execute(spec, {"table_0": long_table})
        assert r1.view_id == r2.view_id
        assert list(r1.data["城市"]) == ["上海", "北京", "深圳"]  # 合计行已排除
        assert list(r1.data["上海" == r1.data["城市"]]["销售额"]) == [350.0]
        assert r1.rows == 3
        assert {"城市", "销售额"} <= set(r1.data.columns)

    def test_exclude_total_and_pivot_shape(self, engine, long_table):
        """透视/宽化：月 × 城市矩阵，一行一个时间点。"""
        spec = ViewSpec(
            kind="sql",
            sql=("select 月份, sum(case when 城市 = '北京' then 销售额 else 0 end) as 北京, "
                 "sum(case when 城市 != '北京' then 销售额 else 0 end) as 其他 "
                 "from table_0 where 城市 != '合计' group by 月份 order by 月份"),
            inputs=["table_0"],
        )
        result = engine.execute(spec, {"table_0": long_table})
        assert list(result.data.columns) == ["月份", "北京", "其他"]
        assert result.rows == 3

    def test_fingerprint_change_changes_id(self, engine, long_table):
        """数据变了 → 指纹变 → view_id 变（缓存 miss 的根基）。"""
        spec = ViewSpec(kind="sql", sql=SQL_BY_CITY, inputs=["table_0"])
        r1 = engine.execute(spec, {"table_0": long_table})
        changed = long_table.copy()
        changed.loc[0, "销售额"] = 12345.0
        r2 = engine.execute(spec, {"table_0": changed})
        assert r1.view_id != r2.view_id

    def test_row_reorder_changes_id_but_not_output(self, engine, long_table):
        """指纹区分输入字节序：换行序 → 新 view_id（内容寻址），但 spec 的 ORDER BY
        保证输出仍完全一致——id 有区分度、结果无漂移。"""
        spec = ViewSpec(kind="sql", sql=SQL_BY_CITY, inputs=["table_0"])
        r1 = engine.execute(spec, {"table_0": long_table})
        reordered = long_table.sample(frac=1.0, random_state=7).reset_index(drop=True)
        r2 = engine.execute(spec, {"table_0": reordered})
        assert r1.view_id != r2.view_id
        pd.testing.assert_frame_equal(r1.data, r2.data)


class TestErrorCodes:
    def test_missing_input(self, engine):
        spec = ViewSpec(kind="sql", sql=SQL_BY_CITY, inputs=["table_0"])
        with pytest.raises(DataViewError) as e:
            engine.execute(spec, {})
        assert e.value.code == "INPUT_NOT_FOUND"

    def test_input_must_be_dataframe(self, engine):
        spec = ViewSpec(kind="sql", sql=SQL_BY_CITY, inputs=["table_0"])
        with pytest.raises(DataViewError) as e:
            engine.execute(spec, {"table_0": [1, 2, 3]})
        assert e.value.code == INPUT_INVALID

    def test_table_name_injection(self, engine, long_table):
        """表名只能由字母/数字/下划线组成（注册进 SQLite 前拦截）。"""
        spec = ViewSpec(kind="sql", sql="select a from t0 order by a",
                        inputs=["`t0; drop table x`"])
        with pytest.raises(DataViewError) as e:
            engine.execute(spec, {"`t0; drop table x`": long_table})
        assert e.value.code == INPUT_INVALID

    def test_sql_error_reported(self, engine, long_table):
        spec = ViewSpec(
            kind="sql",
            sql="select 不存在的列 from table_0 group by 不存在的列 order by 不存在的列",
            inputs=["table_0"],
        )
        with pytest.raises(DataViewError) as e:
            engine.execute(spec, {"table_0": long_table})
        assert e.value.code == "EXEC_ERROR" or e.value.code == SPEC_INVALID

    def test_empty_result_rejected_by_default(self, engine, long_table):
        spec = ViewSpec(
            kind="sql",
            sql="select 城市 from table_0 where 城市 = '火星' order by 城市",
            inputs=["table_0"],
        )
        with pytest.raises(DataViewError) as e:
            engine.execute(spec, {"table_0": long_table})
        assert e.value.code == EMPTY_RESULT

    def test_empty_allowed_when_declared(self, engine, long_table):
        spec = ViewSpec(
            kind="sql",
            sql="select 城市 from table_0 where 城市 = '火星' order by 城市",
            inputs=["table_0"],
            allow_empty=True,
        )
        result = engine.execute(spec, {"table_0": long_table})
        assert result.rows == 0

    def test_row_limit_reached(self, long_table):
        engine = DataViewEngine(max_rows=2)
        spec = ViewSpec(kind="sql", sql=SQL_BY_CITY, inputs=["table_0"])
        with pytest.raises(DataViewError) as e:
            engine.execute(spec, {"table_0": long_table})
        assert e.value.code == ROW_LIMIT_EXCEEDED

    def test_row_limit_allows_aggregated_output(self, long_table):
        """上限只针对输出行数：明细 6 行也能聚合成 3 行通过。"""
        engine = DataViewEngine(max_rows=100)
        spec = ViewSpec(kind="sql", sql=SQL_BY_CITY, inputs=["table_0"])
        assert engine.execute(spec, {"table_0": long_table}).rows == 3

    def test_unknown_mode(self, engine, long_table):
        spec = ViewSpec(kind="sql", sql=SQL_BY_CITY, inputs=["table_0"])
        with pytest.raises(DataViewError) as e:
            engine.execute(spec, {"table_0": long_table}, mode="dry_run")
        assert e.value.code == INPUT_INVALID

    def test_materialize_requires_datasets_dir(self, engine, long_table):
        spec = ViewSpec(kind="sql", sql=SQL_BY_CITY, inputs=["table_0"])
        with pytest.raises(DataViewError) as e:
            engine.execute(spec, {"table_0": long_table}, mode="materialize")
        assert e.value.code == INPUT_INVALID


class TestPluginExecution:
    def _registry(self, version: int = 1, schema: list | None = None):
        def apply(df: pd.DataFrame, params: dict) -> pd.DataFrame:
            n = int(params.get("n", 2))
            out = df.head(n).copy()
            out["已处理"] = [f"n={n}"] * len(out)
            return out

        return PluginRegistry(), None, apply, schema

    def _registry_with(self, schema: list | None = None) -> PluginRegistry:
        def apply(df: pd.DataFrame, params: dict) -> pd.DataFrame:
            out = df.head(2).copy()
            if "drop_col" in params and params.get("drop_col"):
                out = out.drop(columns=params["drop_col"])
            if "extra_col" in params:
                out[params["extra_col"]] = 1
            return out

        reg = PluginRegistry()
        reg.register_entry(
            "slice_head", PluginEntry(
                name="slice_head", version=3, apply=apply, schema=schema or [], path="(test)"
            )
        )
        return reg

    def test_plugin_applied_with_params(self, engine, long_table):
        engine2 = DataViewEngine(registry=self._registry_with())
        spec = ViewSpec(kind="plugin", plugin="slice_head", plugin_version=3,
                        params={"extra_col": "标记"}, inputs=["t"])
        result = engine2.execute(spec, {"t": long_table})
        assert result.rows == 2
        assert result.plugin_version == 3
        assert result.data["标记"].tolist() == [1, 1]

    def test_plugin_not_found(self, engine, long_table):
        engine2 = DataViewEngine(registry=PluginRegistry())  # 空注册表
        spec = ViewSpec(kind="plugin", plugin="不存在", inputs=["t"])
        with pytest.raises(DataViewError) as e:
            engine2.execute(spec, {"t": long_table})
        assert e.value.code == PLUGIN_NOT_FOUND

    def test_plugin_version_mismatch(self, engine, long_table):
        engine2 = DataViewEngine(registry=self._registry_with())
        spec = ViewSpec(kind="plugin", plugin="slice_head", plugin_version=99, inputs=["t"])
        with pytest.raises(DataViewError) as e:
            engine2.execute(spec, {"t": long_table})
        assert e.value.code == PLUGIN_NOT_FOUND

    def test_plugin_schema_mismatch(self, long_table):
        engine = DataViewEngine(registry=self._registry_with(
            schema=[{"name": "不存在列", "role": "time"}]
        ))
        spec = ViewSpec(kind="plugin", plugin="slice_head", plugin_version=3, inputs=["t"])
        with pytest.raises(DataViewError) as e:
            engine.execute(spec, {"t": long_table})
        assert e.value.code == SCHEMA_MISMATCH

    def test_plugin_runtime_error(self, long_table):
        def apply(df: pd.DataFrame, params: dict) -> pd.DataFrame:
            raise ValueError("boom")

        reg = PluginRegistry()
        reg.register_entry(
            "boom", PluginEntry(name="boom", version=1, apply=apply, schema=[], path="(test)")
        )
        engine = DataViewEngine(registry=reg)
        spec = ViewSpec(kind="plugin", plugin="boom", plugin_version=1, inputs=["t"])
        with pytest.raises(DataViewError) as e:
            engine.execute(spec, {"t": long_table})
        assert e.value.code == EXEC_ERROR

    def test_plugin_must_return_dataframe(self, long_table):
        reg = PluginRegistry()
        reg.register_entry(
            "bad", PluginEntry(
                name="bad", version=1, apply=lambda df, p: [1, 2], schema=[], path="(test)"
            )
        )
        engine = DataViewEngine(registry=reg)
        spec = ViewSpec(kind="plugin", plugin="bad", plugin_version=1, inputs=["t"])
        with pytest.raises(DataViewError) as e:
            engine.execute(spec, {"t": long_table})
        assert e.value.code == SCHEMA_MISMATCH


class TestHashConsistency:
    def test_engine_id_matches_manual_compute(self, engine, long_table):
        """engine 绑定 view_id 与外部 spec+指纹计算一致（契约可见）。"""
        spec = ViewSpec(kind="sql", sql=SQL_BY_CITY, inputs=["table_0"])
        result = engine.execute(spec, {"table_0": long_table})
        from service.data_view import fingerprint_dataframe

        manual = view_id(spec, {"table_0": fingerprint_dataframe(long_table)})
        assert result.view_id == manual
