"""runtime 清理 API

POST /api/cleanup?max_age_days=7  手动清理超期 runtime 文件。
"""

from flask import Blueprint, request, jsonify

from Entity import ErrorResponse
from api.common import check_api_key, monitor_response
from service.runtime.runtime_cleanup import cleanup_runtime

bp = Blueprint("cleanup_api", __name__)


@bp.route("/api/cleanup", methods=["POST"])
@monitor_response("cleanup:runtime")
def cleanup_api():
    """清理超期 runtime 文件（uploads/datasets/traces/charts）"""
    err = check_api_key()
    if err:
        return err
    try:
        max_age_days = max(0, int(request.args.get("max_age_days", 7)))
    except ValueError:
        return jsonify(ErrorResponse(detail="max_age_days 必须是整数").model_dump()), 400
    stats = cleanup_runtime(max_age_days=max_age_days)
    return jsonify({
        "detail": f"清理完成（超 {max_age_days} 天）",
        "max_age_days": max_age_days,
        **stats,
        "bytes_freed_mb": round(stats["bytes_freed"] / 1024 / 1024, 2),
    }), 200
