"""
健康检查 API

GET /api/health   存活探针（liveness）：进程活着就返回 200，附带任务队列概况
GET /api/ready    就绪探针（readiness）：运行目录可写 + 对话库可访问，未就绪返回 503

部署探针不应携带 API Key，因此这两个端点**不做鉴权**，且不返回任何密钥类信息。
"""
import os
import time
from collections import Counter
from importlib.metadata import PackageNotFoundError, version as _pkg_version
from pathlib import Path

from flask import Blueprint, jsonify

from api.common import get_charts_dir, get_tasks, get_tasks_lock, get_upload_dir


health_bp = Blueprint("health", __name__, url_prefix="/api")

_START_TIME = time.time()
_TERMINAL_STATES = {"success", "failed", "cancelled"}


def _package_version() -> str:
    """读取已安装包版本，取不到时回退 unknown。"""
    try:
        return _pkg_version("data-visual-server")
    except PackageNotFoundError:
        return "unknown"


def _task_counts(tasks: dict) -> dict:
    """按状态统计任务数（只读快照，持有 task lock）。"""
    with get_tasks_lock():
        counter = Counter(str(t.get("status") or "unknown") for t in tasks.values())
        total = len(tasks)
    counts = {state: counter.get(state, 0) for state in ("pending", "running", "success", "failed", "cancelled")}
    counts["total"] = total
    counts["finished"] = sum(counter.get(s, 0) for s in _TERMINAL_STATES)
    return counts


@health_bp.route("/health", methods=["GET"])
def health():
    """存活探针：进程可达即 200。"""
    return jsonify({
        "status": "ok",
        "version": _package_version(),
        "uptime_seconds": round(time.time() - _START_TIME, 1),
        "pid": os.getpid(),
        "tasks": _task_counts(get_tasks()),
    }), 200


@health_bp.route("/ready", methods=["GET"])
def ready():
    """就绪探针：运行目录可写且对话库可访问才算就绪，否则 503。"""
    checks: dict[str, dict] = {}

    for name, path in (
        ("upload_dir", get_upload_dir()),
        ("charts_dir", get_charts_dir()),
    ):
        p = Path(path)
        ok = p.exists() and os.access(p, os.W_OK)
        checks[name] = {"path": str(p), "ok": ok}
        if not ok:
            try:
                p.mkdir(parents=True, exist_ok=True)
                checks[name]["ok"] = os.access(p, os.W_OK)
            except OSError:
                checks[name]["ok"] = False

    db_ok = True
    db_error = ""
    try:
        from service.runtime.conversation_store import count_conversations

        count_conversations()
    except Exception as e:
        db_ok = False
        db_error = f"{type(e).__name__}: {e}"
    checks["conversation_db"] = {"ok": db_ok}
    if db_error:
        checks["conversation_db"]["error"] = db_error

    all_ok = all(item["ok"] for item in checks.values())
    return jsonify({
        "status": "ready" if all_ok else "not_ready",
        "checks": checks,
    }), 200 if all_ok else 503
