"""
任务查询 API

GET /api/task/<task_id>   查询异步任务状态
"""
from flask import Blueprint, jsonify
from Entity import ErrorResponse
from api.common import check_api_key, get_tasks, get_tasks_lock, request_cancel


task_bp = Blueprint("task", __name__, url_prefix="/api")


@task_bp.route("/task/<task_id>", methods=["GET"])
def get_task(task_id):
    auth_error = check_api_key()
    if auth_error:
        return auth_error

    with get_tasks_lock():
        task = get_tasks().get(task_id)
        if not task:
            return jsonify(ErrorResponse(detail="Task not found").dict()), 404
        payload = dict(task)

    payload["task_id"] = task_id
    return jsonify(payload), 200


@task_bp.route("/task/<task_id>/cancel", methods=["POST"])
def cancel_task(task_id: str):
    """取消任务"""
    err = check_api_key()
    if err:
        return err

    tasks = get_tasks()
    with get_tasks_lock():
        if task_id not in tasks:
            return jsonify({"detail": "Task not found"}), 404

        task = tasks[task_id]
        current_status = task.get("status", "")
        if current_status in ("success", "failed", "cancelled"):
            return jsonify({"detail": f"Task already {current_status}"}), 400

        # 标记取消
        request_cancel(task_id)

    return jsonify({"detail": "Cancel requested", "task_id": task_id}), 202
