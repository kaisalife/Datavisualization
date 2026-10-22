"""会话门面：dataset_id 解析、表别名、describe / run_view、路径穿越拒绝。"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from service.data_view import DataViewError, ViewSpec
from service.data_view import INPUT_INVALID, INPUT_NOT_FOUND
from service.data_view.session import (
    describe_dataset,
    list_dataset_tables,
    resolve_dataset_dir,
    run_view,
)
from service.data_ingestion.models import RawTable
from service.data_ingestion.series import build_series_catalog


SQL_BY_MONTH = (
    "select 月份, sum(销售额) as 销售额 from table_0 "
    "group by 月份 order by 月份"
)


@pytest.fixture
def raw_frame() -> pd.DataFrame:
    """明细长表：城市 × 月份 × 销售额，含合计行。"""
    return pd.DataFrame(
        {
            "城市": ["北京", "北京", "上海", "上海", "合计"],
            "月份": ["1 月", "2 月", "1 月", "2 月", "3 月"],
            "销售额": [100.0, 200.0, 300.0, 50.0, 588.0],
        }
    )


@pytest.fixture
def session_dir(tmp_path: Path, raw_frame: pd.DataFrame) -> Path:
    """模拟一个已接入的数据会话：raw 表 + identity series + manifest。"""
    d = tmp_path / "ds_ab12cd34ef56"
    d.mkdir()
    raw = d / "raw"
    raw.mkdir()
    raw_frame.reset_index(drop=True).to_parquet(raw / "raw_0.parquet", index=False)
    (raw / "manifest.json").write_text(
        json.dumps(
            [
                {"index": 0, "name": "销售明细", "rows": 5,
                 "columns": ["城市", "月份", "销售额"]}
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    build_series_catalog(
        [RawTable(name="销售明细", df=raw_frame, source_kind="file", source_path="x.csv")], d
    )
    return d


def _spec(**override) -> dict:
    base = {"kind": "sql", "inputs": ["table_0"], "sql": SQL_BY_MONTH}
    base.update(override)
    return base


class TestResolveDatasetDir:
    def test_bad_format_rejected(self, tmp_path: Path):
        with pytest.raises(DataViewError) as e:
            resolve_dataset_dir("../runtime/datasets", datasets_root=tmp_path)
        assert e.value.code == INPUT_INVALID
        with pytest.raises(DataViewError) as e2:
            resolve_dataset_dir("ds_uppercase!", datasets_root=tmp_path)
        assert e2.value.code == INPUT_INVALID

    def test_missing_session_rejected(self, tmp_path: Path):
        with pytest.raises(DataViewError) as e:
            resolve_dataset_dir("ds_000000000000", datasets_root=tmp_path)
        assert e.value.code == INPUT_NOT_FOUND

    def test_valid_session(self, session_dir: Path, tmp_path: Path):
        assert resolve_dataset_dir("ds_ab12cd34ef56", datasets_root=tmp_path) == session_dir


class TestListTables:
    def test_raw_first_then_series(self, session_dir: Path, tmp_path: Path):
        tables = list_dataset_tables("ds_ab12cd34ef56", datasets_root=tmp_path)
        raws = [t for t in tables if t["origin"] == "raw"]
        series = [t for t in tables if t["origin"] == "series"]
        assert raws and raws[0]["alias"] == "table_0"
        assert raws[0]["name"] == "销售明细"
        assert raws[0]["rows"] == 5
        assert "销售额" in raws[0]["columns"]
        assert series and all(t["alias"].startswith("series_") for t in series)
        aliases = sorted(t["alias"] for t in series)
        assert aliases == sorted(set(aliases))  # 无重复别名

    def test_no_raw_falls_back_to_series(self, session_dir: Path, tmp_path: Path):
        import shutil

        shutil.rmtree(session_dir / "raw")
        tables = list_dataset_tables("ds_ab12cd34ef56", datasets_root=tmp_path)
        assert tables, "series 兜底必须保证还有可查询输入"
        assert all(t["origin"] == "series" for t in tables)


class TestDescribe:
    def test_tables_columns_sample_views(self, session_dir: Path, tmp_path: Path):
        info = describe_dataset("ds_ab12cd34ef56", datasets_root=tmp_path)
        assert info["dataset_id"] == "ds_ab12cd34ef56"
        assert info["tables"][0]["sample"][0]["城市"] == "北京"
        dtypes = {c["name"]: c["dtype"] for c in info["tables"][0]["columns"]}
        assert "销售额" in dtypes and "float" in dtypes["销售额"]
        assert info["views"] == []

    def test_views_listed_after_materialize(self, session_dir: Path, tmp_path: Path):
        run_view("ds_ab12cd34ef56", _spec(), mode="materialize", datasets_root=tmp_path)
        info = describe_dataset("ds_ab12cd34ef56", datasets_root=tmp_path)
        assert len(info["views"]) == 1
        assert "order by" in info["views"][0]["spec_summary"].lower()


class TestRunView:
    def test_materialize_and_series_inputs(self, session_dir: Path, tmp_path: Path):
        payload = run_view("ds_ab12cd34ef56", _spec(), datasets_root=tmp_path)
        assert payload["view_id"].startswith("vw_")
        assert payload["rows"] == 3
        names = [c["name"] for c in payload["schema"]]
        assert names == ["月份", "销售额"]
        assert payload["parquet_path"]
        tables = {t["alias"]: t for t in list_dataset_tables(
            "ds_ab12cd34ef56", datasets_root=tmp_path
        )}
        assert "series_0" in tables

    def test_preview_no_files(self, session_dir: Path, tmp_path: Path):
        payload = run_view("ds_ab12cd34ef56", _spec(), mode="preview", datasets_root=tmp_path)
        assert payload["rows"] == 3
        assert not (session_dir / "views").exists(), "preview 不落盘"

    def test_second_run_cache_hit(self, session_dir: Path, tmp_path: Path):
        first = run_view("ds_ab12cd34ef56", _spec(), datasets_root=tmp_path)
        second = run_view("ds_ab12cd34ef56", _spec(), datasets_root=tmp_path)
        assert second["view_id"] == first["view_id"]
        assert second.get("cached") is True

    def test_view_alias_input(self, session_dir: Path, tmp_path: Path):
        """identity series 也可以作为 SQL 输入（宽表 月份 × 城市）。"""
        series_tables = [
            t for t in list_dataset_tables("ds_ab12cd34ef56", datasets_root=tmp_path)
            if t["origin"] == "series"
        ]
        alias = series_tables[0]["alias"]
        spec = {
            "kind": "sql",
            "inputs": [alias],
            "sql": f"select \"月份\" as 月份 from [{alias}] order by 月份",
        }
        payload = run_view("ds_ab12cd34ef56", spec, datasets_root=tmp_path)
        assert payload["rows"] == 3

    def test_unknown_alias_rejected_with_available(self, session_dir: Path, tmp_path: Path):
        with pytest.raises(DataViewError) as e:
            run_view("ds_ab12cd34ef56", _spec(inputs=["不存在的表"]), datasets_root=tmp_path)
        assert e.value.code == INPUT_NOT_FOUND
        assert "table_0" in str(e.value)

    def test_bad_sql_structured_error(self, session_dir: Path, tmp_path: Path):
        with pytest.raises(DataViewError) as e:
            run_view(
                "ds_ab12cd34ef56",
                _spec(sql="select 月份, sum(销售额) as s from table_0 group by 月份"),
                datasets_root=tmp_path,
            )
        assert e.value.code == "UNORDERED_OUTPUT"
        with pytest.raises(DataViewError) as e2:
            run_view(
                "ds_ab12cd34ef56",
                _spec(sql="select 城市 from table_0 where 城市 = '火星' order by 城市",
                      allow_empty=False),
                datasets_root=tmp_path,
            )
        assert e2.value.code == "EMPTY_RESULT"
        # 失败不落盘
        assert not (session_dir / "views").exists()


class TestPathSafety:
    def test_series_path_escape_rejected(self, session_dir: Path, tmp_path: Path):
        """manifest 里 series data_path 指向会话外 → 拒绝（防路径穿越）。"""
        manifest_path = session_dir / "manifest.json"
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        data["series"][0]["data_path"] = "C:/Windows/evil.parquet"
        manifest_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(DataViewError) as e:
            run_view(
                "ds_ab12cd34ef56",
                {
                    "kind": "sql",
                    "inputs": ["series_0"],
                    "sql": "select * from series_0 order by 1",
                },
                datasets_root=tmp_path,
            )
        assert e.value.code == INPUT_INVALID

    def test_raw_index_escape_rejected(self, session_dir: Path, tmp_path: Path):
        """raw manifest 的 index 必须是数字内别名；注入别名走默认拒绝。"""
        manifest_path = session_dir / "raw" / "manifest.json"
        meta = [{"index": 0, "name": "销售明细", "rows": 5, "columns": []},
                {"index": 1, "name": "x", "rows": 0, "columns": []}]
        manifest_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(DataViewError) as e:
            run_view(
                "ds_ab12cd34ef56",
                _spec(inputs=["raw_0"]),  # 只有 table_* 别名合法
                datasets_root=tmp_path,
            )
        assert e.value.code == INPUT_NOT_FOUND
