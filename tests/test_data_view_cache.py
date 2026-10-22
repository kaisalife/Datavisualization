"""缓存：同 spec 命中、数据变更自动失效、失败不落盘、幂等复用。"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from service.data_view import (
    DataViewEngine,
    DataViewError,
    PluginEntry,
    PluginRegistry,
    ViewSpec,
    list_views,
    load_cached,
    materialize_view,
)


SQL_BY_MONTH = (
    "select 月份, sum(销售额) as 销售额 from table_0 "
    "where 城市 != '合计' group by 月份 order by 月份"
)


@pytest.fixture
def long_table() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "城市": ["北京", "北京", "上海", "上海", "合计", "深圳"],
            "月份": ["1 月", "1 月", "2 月", "2 月", "3 月", "3 月"],
            "销售额": [100.0, 200.0, 300.0, 50.0, 9999.0, 20.0],
        }
    )


@pytest.fixture
def datasets_dir(tmp_path: Path) -> Path:
    d = tmp_path / "ds_ab12cd34ef56"
    d.mkdir()
    return d


@pytest.fixture
def engine() -> DataViewEngine:
    return DataViewEngine()


def _spec() -> ViewSpec:
    return ViewSpec(kind="sql", sql=SQL_BY_MONTH, inputs=["table_0"], title="按月合计")


class TestMaterialize:
    def test_writes_parquet_and_manifest(self, engine, long_table, datasets_dir):
        result = engine.execute(_spec(), {"table_0": long_table})
        path = materialize_view(_spec(), result, datasets_dir)
        assert Path(path).exists()
        manifest_path = Path(path).with_suffix(".manifest.json")
        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["view_id"] == result.view_id
        assert manifest["rows"] == result.rows
        assert manifest["spec"]["inputs"] == ["table_0"]
        assert manifest["inputs_fingerprints"]["table_0"]

    def test_execute_materialize_mode(self, engine, long_table, datasets_dir):
        """engine 直连 materialize 模式写盘并标注 cached/路径。"""
        result = engine.execute(
            _spec(), {"table_0": long_table}, mode="materialize", datasets_dir=str(datasets_dir)
        )
        assert result.extra["materialized"] is True
        assert Path(result.extra["parquet_path"]).exists()

    def test_same_id_reuses_without_rewrite(self, engine, long_table, datasets_dir):
        """同 id 第二次物化命中且不重写（内容寻址幂等）。"""
        r1 = engine.execute(_spec(), {"table_0": long_table})
        p1 = materialize_view(_spec(), r1, datasets_dir)
        before = (Path(p1).stat().st_mtime_ns, Path(p1).read_bytes())
        r2 = engine.execute(_spec(), {"table_0": long_table})
        p2 = materialize_view(_spec(), r2, datasets_dir)
        assert p1 == p2
        after = (Path(p2).stat().st_mtime_ns, Path(p2).read_bytes())
        assert before == after  # 未重写

    def test_requires_existing_datasets_dir(self, engine, long_table, tmp_path):
        result = engine.execute(_spec(), {"table_0": long_table})
        with pytest.raises(DataViewError) as e:
            materialize_view(_spec(), result, tmp_path / "不存在目录")
        assert e.value.code == "INPUT_INVALID"


class TestCacheHitAndMiss:
    def test_load_cached_hit(self, engine, long_table, datasets_dir):
        result = engine.execute(_spec(), {"table_0": long_table})
        materialize_view(_spec(), result, datasets_dir)
        cached = load_cached(datasets_dir, result.view_id)
        assert cached is not None and cached.exists()

    def test_load_cached_partial_is_miss(self, engine, long_table, datasets_dir):
        """只有 parquet 没有 manifest 不算命中（防残缺缓存误导）。"""
        result = engine.execute(_spec(), {"table_0": long_table})
        materialize_view(_spec(), result, datasets_dir)
        (datasets_dir / "views" / f"{result.view_id}.manifest.json").unlink()
        assert load_cached(datasets_dir, result.view_id) is None

    def test_data_change_produces_new_id_and_file(self, engine, long_table, datasets_dir):
        """数据变了：新 view_id 新文件；旧产物原样保留（不可变原则）。"""
        r1 = engine.execute(_spec(), {"table_0": long_table}, mode="materialize",
                            datasets_dir=str(datasets_dir))
        changed = long_table.copy()
        changed.loc[0, "销售额"] = 888.0
        r2 = engine.execute(_spec(), {"table_0": changed}, mode="materialize",
                            datasets_dir=str(datasets_dir))
        assert r1.view_id != r2.view_id
        assert Path(r1.extra["parquet_path"]).exists()      # 旧产物不删
        assert Path(r2.extra["parquet_path"]).exists()
        # 两个文件的数值各自独立
        df1 = pd.read_parquet(r1.extra["parquet_path"])
        df2 = pd.read_parquet(r2.extra["parquet_path"])
        assert df1.loc[df1["月份"] == "1 月", "销售额"].iloc[0] == 300.0
        # 888 + 200 = 1088：第一行北京 1 月被改成 888
        assert df2.loc[df2["月份"] == "1 月", "销售额"].iloc[0] == 1088.0


class TestNoCacheOnFailure:
    def test_failed_execution_writes_nothing(self, engine, long_table, datasets_dir):
        bad_spec = ViewSpec(
            kind="sql",
            sql="select 月份 from table_0 where 城市 = '火星' order by 月份",
            inputs=["table_0"],
        )
        with pytest.raises(DataViewError):
            engine.execute(bad_spec, {"table_0": long_table}, mode="materialize",
                           datasets_dir=str(datasets_dir))
        # views 目录只为成功产物创建（未创建或为空）
        views = datasets_dir / "views"
        assert not views.exists() or not any(views.iterdir())

    def test_failed_plugin_writes_nothing(self, long_table, datasets_dir):
        def apply(df: pd.DataFrame, params: dict) -> pd.DataFrame:
            raise RuntimeError("半路炸掉")

        reg = PluginRegistry()
        reg.register_entry(
            "halfway", PluginEntry(name="halfway", version=1, apply=apply, schema=[], path="(t)")
        )
        engine = DataViewEngine(registry=reg)
        spec = ViewSpec(kind="plugin", plugin="halfway", plugin_version=1, inputs=["t"])
        with pytest.raises(DataViewError):
            engine.execute(spec, {"t": long_table}, mode="materialize",
                           datasets_dir=str(datasets_dir))
        views = datasets_dir / "views"
        assert not views.exists() or not any(views.iterdir())


class TestListViews:
    def test_list_after_materialize(self, engine, long_table, datasets_dir):
        r1 = engine.execute(_spec(), {"table_0": long_table}, mode="materialize",
                            datasets_dir=str(datasets_dir))
        items = list_views(datasets_dir)
        assert len(items) == 1
        assert items[0]["view_id"] == r1.view_id
        assert items[0]["rows"] == r1.rows
        assert "销售额" in items[0]["columns"]
        assert "order by" in items[0]["spec_summary"].lower().replace("[无排序]", "")

    def test_list_empty_when_no_views(self, engine, datasets_dir):
        assert list_views(datasets_dir) == []


class TestParquetMatchesResult:
    def test_parquet_value_equals_result(self, engine, long_table, datasets_dir):
        """真机验收口径的根基：物化文件与内存结果逐值一致。"""
        result = engine.execute(_spec(), {"table_0": long_table}, mode="materialize",
                                datasets_dir=str(datasets_dir))
        df = pd.read_parquet(result.extra["parquet_path"])
        pd.testing.assert_frame_equal(df, result.data)
