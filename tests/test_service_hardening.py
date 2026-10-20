"""服务化加固测试（无需 LLM / 网络）。

覆盖：
- api.common.prune_tasks：过期清理、容量上限、进行中任务不清理
- 部署探针：GET /api/health、GET /api/ready（不鉴权）
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta

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
