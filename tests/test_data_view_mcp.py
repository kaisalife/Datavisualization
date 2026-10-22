"""MCP 薄适配器：工具参数校验、句柄解析、失败结构化返回（不启动 server）。"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from agent_tools.tool_data_view import describe_dataset, run_view
from service.data_ingestion.models import RawTable
from service.data_ingestion.series import build_series_catalog


@pytest.fixture
def env_root(tmp_path: Path, monkeypatch) -> Path:
    """把数据根目录重定向到临时目录（MCP 子进程同样读 env）。"""
    monkeypatch.setenv("TEMP_DATASETS_DIR", str(tmp_path))
    d = tmp_path / "ds_1a2b3c4d5e6f"
    d.mkdir()
    df = pd.DataFrame({"城市": ["北京", "上海", "广州"], "销售额": [10.0, 20.0, 30.0]})
    raw = d / "raw"
    raw.mkdir()
    df.to_parquet(raw / "raw_0.parquet", index=False)
    (raw / "manifest.json").write_text(
        json.dumps([{"index": 0, "name": "销售明细", "rows": 3,
                     "columns": ["城市", "销售额"]}], ensure_ascii=False),
        encoding="utf-8",
    )
    build_series_catalog(
        [RawTable(name="销售明细", df=df, source_kind="file", source_path="x.csv")], d
    )
    return tmp_path


def _unwrapped(obj):
    """fastmcp @tool 包装后的原始函数（default='...' 形式的 fn）。"""
    inner = getattr(obj, "fn", None)
    return inner if callable(inner) else obj


class TestDescribeDatasetTool:
    def test_valid_dataset(self, env_root: Path):
        out = _unwrapped(describe_dataset)("ds_1a2b3c4d5e6f")
        payload = json.loads(out)
        assert payload["ok"] is True
        assert payload["tables"][0]["alias"] == "table_0"

    def test_invalid_dataset_structured_error(self, env_root: Path):
        out = _unwrapped(describe_dataset)("../../etc")
        payload = json.loads(out)
        assert payload["ok"] is False
        assert payload["code"] == "INPUT_INVALID"

    def test_missing_session_structured_error(self, env_root: Path):
        out = _unwrapped(describe_dataset)("ds_000000000000")
        payload = json.loads(out)
        assert payload["ok"] is False
        assert payload["code"] == "INPUT_NOT_FOUND"


class TestRunViewTool:
    def test_materialize(self, env_root: Path):
        out = _unwrapped(run_view)(
            "ds_1a2b3c4d5e6f",
            {"kind": "sql", "inputs": ["table_0"],
             "sql": "select 城市, sum(销售额) as 销售额 from table_0 "
                    "group by 城市 order by 销售额 desc"},
        )
        payload = json.loads(out)
        assert payload["ok"] is True
        assert payload["view_id"].startswith("vw_")
        assert payload["rows"] == 3

    def test_write_rejected_with_hint(self, env_root: Path):
        out = _unwrapped(run_view)(
            "ds_1a2b3c4d5e6f",
            {"kind": "sql", "inputs": ["table_0"],
             "sql": "select 1 from table_0 order by 1; drop table x"},
        )
        payload = json.loads(out)
        assert payload["ok"] is False
        assert payload["code"] == "WRITE_STATEMENT_REJECTED"
        assert "hint" in payload

    def test_unordered_rejected(self, env_root: Path):
        out = _unwrapped(run_view)(
            "ds_1a2b3c4d5e6f",
            {"kind": "sql", "inputs": ["table_0"], "sql": "select 城市 from table_0"},
        )
        payload = json.loads(out)
        assert payload["code"] == "UNORDERED_OUTPUT"

    def test_preview_mode_no_write(self, env_root: Path):
        out = _unwrapped(run_view)(
            "ds_1a2b3c4d5e6f",
            {"kind": "sql", "inputs": ["table_0"],
             "sql": "select 城市 from table_0 order by 城市"},
            mode="preview",
        )
        payload = json.loads(out)
        assert payload["ok"] is True
        assert not (env_root / "ds_1a2b3c4d5e6f" / "views").exists()

    def test_unknown_mode_structured_error(self, env_root: Path):
        out = _unwrapped(run_view)(
            "ds_1a2b3c4d5e6f",
            {"kind": "sql", "inputs": ["table_0"],
             "sql": "select 城市 from table_0 order by 城市"},
            mode="dry_run",
        )
        payload = json.loads(out)
        assert payload["ok"] is False
