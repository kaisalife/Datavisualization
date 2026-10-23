"""任务级指标：JSONL 追加 + 汇总 + API（无 LLM）。"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from service.runtime.task_metrics import (
    record_task_metrics,
    summarize_task_metrics,
)

pytestmark = pytest.mark.whitebox


@pytest.fixture
def metrics_path(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / "task_metrics.jsonl"
    monkeypatch.setenv("TASK_METRICS_PATH", str(path))
    return path


def _record(task_id: str, status: str, duration: float, charts: int = 1, failed: int = 0):
    record_task_metrics(
        task_id=task_id,
        status=status,
        duration_s=duration,
        model="test-model",
        charts=charts,
        failed_plans=failed,
        stages=[
            {"name": "plan", "label": "计划生成", "duration_s": duration * 0.3, "status": "success"},
            {"name": "chart_1", "label": "图表 1", "duration_s": duration * 0.6, "status": "success"},
        ],
    )


class TestTaskMetrics:
    def test_record_and_summarize(self, metrics_path: Path):
        _record("t1", "success", 10, charts=2)
        _record("t2", "success", 20, charts=2)
        _record("t3", "failed", 30, charts=0, failed=2)

        summary = summarize_task_metrics(days=7, slow_limit=5)

        assert summary["tasks"] == 3
        assert summary["status"]["success"] == 2
        assert summary["status"]["failed"] == 1
        assert summary["success_rate"] == pytest.approx(2 / 3, abs=1e-4)
        assert summary["duration_s"]["p50"] == 20
        assert summary["duration_s"]["p95"] == 30
        assert summary["duration_s"]["max"] == 30
        assert summary["charts"]["total"] == 4
        assert summary["failed_plans"] == 2
        assert summary["slowest"][0]["task_id"] == "t3"
        assert summary["slowest"][0]["status"] == "failed"

        stages = {item["name"]: item for item in summary["stages"]}
        assert stages["chart_1"]["count"] == 3
        assert stages["chart_1"]["avg_s"] == pytest.approx(12.0, abs=0.1)

    def test_old_and_corrupt_records_are_ignored(self, metrics_path: Path):
        _record("fresh", "success", 5)
        now = time.time()
        old = {
            "task_id": "old",
            "status": "success",
            "duration_s": 1,
            "finished_ts": now - 30 * 86400,
            "stages": [],
        }
        with metrics_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(old) + "\n")
            handle.write("{not json}\n")

        summary = summarize_task_metrics(days=7)

        assert summary["tasks"] == 1
        assert summary["slowest"][0]["task_id"] == "fresh"

    def test_missing_file_returns_empty_summary(self, metrics_path: Path):
        summary = summarize_task_metrics(days=7)

        assert summary["tasks"] == 0
        assert summary["duration_s"]["p95"] == 0
        assert summary["stages"] == []
        assert summary["slowest"] == []

    def test_api_returns_summary(self, metrics_path: Path):
        import app as app_module

        _record("api-task", "success", 8, charts=1)
        app_module.app.config["_SERVICE_API_KEY"] = ""
        client = app_module.app.test_client()

        resp = client.get("/api/metrics/tasks?days=7&limit=5")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["tasks"] == 1
        assert body["status"]["success"] == 1
        assert body["slowest"][0]["task_id"] == "api-task"
