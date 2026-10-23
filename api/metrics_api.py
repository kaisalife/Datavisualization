"""任务指标聚合 API。

GET /api/metrics/tasks?days=7&limit=10
返回最近 N 天任务的：状态分布、成功率、耗时 p50/p90/p95、最慢任务、阶段耗时。
数据来源是任务完成时追加的 ``runtime/logs/task_metrics.jsonl``（见
``service/runtime/task_metrics.py``）。
"""
from flask import Blueprint, jsonify, request

from api.common import check_api_key, monitor_response
from service.runtime.task_metrics import summarize_task_metrics

metrics_bp = Blueprint("metrics", __name__, url_prefix="/api")


@metrics_bp.route("/metrics/tasks", methods=["GET"])
@monitor_response("metrics:tasks")
def task_metrics():
    """任务指标汇总（只读）。"""
    auth_error = check_api_key()
    if auth_error:
        return auth_error

    try:
        days = float(request.args.get("days", "7"))
    except (TypeError, ValueError):
        days = 7.0
    days = max(1.0, min(days, 90.0))

    try:
        limit = int(request.args.get("limit", "10"))
    except (TypeError, ValueError):
        limit = 10
    limit = max(1, min(limit, 50))

    return jsonify(summarize_task_metrics(days=days, slow_limit=limit)), 200
