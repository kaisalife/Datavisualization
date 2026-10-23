"""服务化加固测试（无需 LLM / 网络）。

覆盖：
- api.common.prune_tasks：过期清理、容量上限、进行中任务不清理
- 部署探针：GET /api/health、GET /api/ready（不鉴权）
"""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from flask import Flask

from api.common import init_app, prune_tasks

pytestmark = pytest.mark.whitebox


def _ts(seconds_ago: float) -> str:
    return (datetime.now() - timedelta(seconds=seconds_ago)).isoformat()


class TestPruneTasks:
    def test_removes_expired_terminal_tasks_only(self):
        tasks = {
            "old_success": {"status": "success", "created_at": _ts(7200)},
            "old_failed": {"status": "failed", "created_at": _ts(4000)},
            "fresh_success": {"status": "success", "created_at": _ts(10)},
            "running": {"status": "running", "created_at": _ts(9000)},
            "pending": {"status": "pending", "created_at": _ts(9000)},
        }

        removed = prune_tasks(tasks, threading.Lock(), retention_seconds=3600, max_entries=500)

        assert removed == 2
        assert set(tasks) == {"fresh_success", "running", "pending"}

    def test_max_entries_evicts_oldest_terminal_first(self):
        tasks = {
            "t1": {"status": "success", "created_at": _ts(300)},
            "t2": {"status": "success", "created_at": _ts(200)},
            "t3": {"status": "success", "created_at": _ts(100)},
            "t4": {"status": "running", "created_at": _ts(1000)},
        }

        prune_tasks(tasks, threading.Lock(), retention_seconds=10**6, max_entries=2)

        assert set(tasks) == {"t3", "t4"}

    def test_retention_zero_clears_terminal_but_keeps_running(self):
        tasks = {
            "done": {"status": "cancelled", "created_at": _ts(1)},
            "running": {"status": "running", "created_at": _ts(1)},
        }

        prune_tasks(tasks, threading.Lock(), retention_seconds=0, max_entries=100)

        assert set(tasks) == {"running"}

    def test_task_without_created_at_is_kept(self):
        tasks = {"legacy": {"status": "success"}}

        prune_tasks(tasks, threading.Lock(), retention_seconds=1, max_entries=100)

        assert set(tasks) == {"legacy"}


@pytest.fixture
def client():
    """用真实 app 蓝图搭最小 Flask 应用（注入空依赖即可满足探针）。"""
    import app as app_module

    return app_module.app.test_client()


class TestHealthEndpoints:
    def test_health_returns_ok(self, client):
        resp = client.get("/api/health")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "ok"
        assert "tasks" in body and body["tasks"]["total"] >= 0


# ---------------------------------------------------------------------------
# 队列过载保护 / 事件循环清理
# ---------------------------------------------------------------------------


def _app_with_tasks(tasks: dict) -> Flask:
    app = Flask(__name__)
    init_app(
        app,
        executor=None,
        tasks=tasks,
        tasks_lock=threading.Lock(),
        upload_dir=Path("."),
        charts_dir=Path("."),
        service_api_key="",
        logger=None,
    )
    return app


class TestQueueBackpressure:
    def test_active_count_excludes_terminal_tasks(self):
        from api.common import active_task_count

        tasks = {
            "run": {"status": "running"},
            "queue": {"status": "pending"},
            "done": {"status": "success"},
            "fail": {"status": "failed"},
        }
        app = _app_with_tasks(tasks)

        with app.app_context():
            assert active_task_count() == 2

    def test_limit_returns_429_with_actionable_detail(self, monkeypatch):
        from api.common import ensure_queue_capacity

        monkeypatch.setenv("TASK_QUEUE_LIMIT", "2")
        tasks = {"a": {"status": "running"}, "b": {"status": "pending"}}
        app = _app_with_tasks(tasks)

        with app.app_context(), app.test_request_context():
            response = ensure_queue_capacity()

        assert response is not None
        payload, status = response
        assert status == 429
        assert "上限" in payload.get_json()["detail"]

    def test_below_limit_and_zero_means_unlimited(self, monkeypatch):
        from api.common import ensure_queue_capacity

        tasks = {"a": {"status": "running"}}
        app = _app_with_tasks(tasks)

        with app.app_context(), app.test_request_context():
            monkeypatch.setenv("TASK_QUEUE_LIMIT", "5")
            assert ensure_queue_capacity() is None
            monkeypatch.setenv("TASK_QUEUE_LIMIT", "0")
            assert ensure_queue_capacity() is None


def test_shutdown_event_loop_cancels_pending_tasks():
    import asyncio

    from api.common import shutdown_event_loop

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    pending = loop.create_task(asyncio.sleep(60))
    loop.run_until_complete(asyncio.sleep(0))  # 让任务真正启动

    shutdown_event_loop(loop)

    assert loop.is_closed()
    assert pending.cancelled() or pending.done()

    def test_ready_reports_checks(self, client):
        resp = client.get("/api/ready")
        body = resp.get_json()

        assert resp.status_code == 200
        assert body["status"] == "ready"
        assert body["checks"]["conversation_db"]["ok"] is True

    def test_health_needs_no_api_key(self):
        """即使配置了 SERVICE_API_KEY，探针也不鉴权。"""
        import app as app_module

        original = app_module.app.config.get("_SERVICE_API_KEY")
        app_module.app.config["_SERVICE_API_KEY"] = "secret"
        try:
            resp = app_module.app.test_client().get("/api/health")
            assert resp.status_code == 200
        finally:
            app_module.app.config["_SERVICE_API_KEY"] = original


def test_init_app_injects_dependencies():
    """init_app 注入的依赖可通过 config 取回（含 tasks 字典对象本体）。"""
    app = Flask(__name__)
    tasks: dict = {}
    init_app(
        app=app,
        executor=None,
        tasks=tasks,
        tasks_lock=threading.Lock(),
        upload_dir=None,
        charts_dir=None,
        service_api_key="",
        logger=None,
    )

    assert app.config["_TASKS"] is tasks

class TestUploadPrune:
    """上传副本的保留期清理（只删过期单文件，不动新文件/目录）。"""

    def _make_upload(self, root: Path, name: str, size: int, age_hours: float) -> Path:
        path = root / name
        path.write_text("x" * size, encoding="utf-8")
        stamp = time.time() - age_hours * 3600
        os.utime(path, (stamp, stamp))
        return path

    def test_removes_only_expired_files(self, tmp_path, monkeypatch):
        from service.runtime.runtime_cleanup import prune_uploads

        uploads = tmp_path / "uploads"
        uploads.mkdir()
        old = self._make_upload(uploads, "old.csv", 100, age_hours=48)
        fresh = self._make_upload(uploads, "fresh.csv", 50, age_hours=1)
        subdir = uploads / "keep_dir"
        subdir.mkdir()
        monkeypatch.setenv("TEMP_UPLOAD_DIR", str(uploads))

        stats = prune_uploads(max_age_hours=24)

        assert stats == {"removed_files": 1, "bytes_freed": 100}
        assert not old.exists()
        assert fresh.exists()
        assert subdir.is_dir()

    def test_zero_disables_pruning(self, tmp_path, monkeypatch):
        from service.runtime.runtime_cleanup import prune_uploads

        uploads = tmp_path / "uploads"
        uploads.mkdir()
        old = self._make_upload(uploads, "old.csv", 10, age_hours=1000)
        monkeypatch.setenv("TEMP_UPLOAD_DIR", str(uploads))

        assert prune_uploads(max_age_hours=0) == {"removed_files": 0, "bytes_freed": 0}
        assert old.exists()

    def test_missing_dir_is_noop(self, tmp_path, monkeypatch):
        from service.runtime.runtime_cleanup import prune_uploads

        monkeypatch.setenv("TEMP_UPLOAD_DIR", str(tmp_path / "missing"))
        assert prune_uploads(max_age_hours=1) == {"removed_files": 0, "bytes_freed": 0}

class TestWarmupFlags:
    def test_rag_warmup_flag_parsing(self, monkeypatch):
        from service.runtime.warmup import _rag_warmup_enabled

        for value in ("1", "true", "YES", "on"):
            monkeypatch.setenv("SERVICE_WARMUP_RAG", value)
            assert _rag_warmup_enabled() is True

        for value in ("0", "false", "no", "off", ""):
            monkeypatch.setenv("SERVICE_WARMUP_RAG", value)
            assert _rag_warmup_enabled() is False
