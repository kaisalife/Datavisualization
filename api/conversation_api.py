"""对话日志 CRUD API

以一轮对话为单位管理日志，支持前端历史对话列表和提示词修改重提。
"""

from flask import Blueprint, request, jsonify, current_app

from Entity import ErrorResponse
from api.common import check_api_key, monitor_response
from service.runtime.conversation_store import (
    list_conversations,
    get_conversation,
    delete_conversation,
    delete_oldest_conversations,
    batch_delete_conversations,
    count_conversations,
    update_prompt,
)

bp = Blueprint("conversation_api", __name__)


@bp.route("/api/conversations", methods=["GET"])
@monitor_response("conversation:list")
def list_conversations_api():
    """列出所有对话（分页）"""
    err = check_api_key()
    if err:
        return err

    limit = min(int(request.args.get("limit", 50)), 200)
    offset = int(request.args.get("offset", 0))

    conversations = list_conversations(limit=limit, offset=offset)
    return jsonify({"conversations": conversations, "total": count_conversations()}), 200


@bp.route("/api/conversations/<conversation_id>", methods=["GET"])
@monitor_response("conversation:get")
def get_conversation_api(conversation_id: str):
    """获取单个对话详情（含完整 agent_logs）"""
    err = check_api_key()
    if err:
        return err

    conv = get_conversation(conversation_id)
    if conv is None:
        return jsonify(ErrorResponse(detail="对话不存在").model_dump()), 404
    return jsonify(conv), 200


@bp.route("/api/conversations/<conversation_id>", methods=["DELETE"])
@monitor_response("conversation:delete")
def delete_conversation_api(conversation_id: str):
    """删除对话"""
    err = check_api_key()
    if err:
        return err

    if delete_conversation(conversation_id):
        return jsonify(ErrorResponse(detail="已删除").model_dump()), 200
    return jsonify(ErrorResponse(detail="对话不存在").model_dump()), 404


@bp.route("/api/conversations/oldest", methods=["DELETE"])
@monitor_response("conversation:delete_oldest")
def delete_oldest_api():
    """删除最早的 N 个对话（联动删图表+trace）"""
    err = check_api_key()
    if err:
        return err
    try:
        count = max(1, min(int(request.args.get("count", 30)), 500))
    except ValueError:
        return jsonify(ErrorResponse(detail="count 必须是整数").model_dump()), 400
    deleted = delete_oldest_conversations(count)
    return jsonify({"detail": f"已删除最老 {deleted} 个对话", "deleted": deleted}), 200


@bp.route("/api/conversations/batch", methods=["DELETE"])
@monitor_response("conversation:batch_delete")
def batch_delete_api():
    """批量删除指定对话（联动删图表+trace）"""
    err = check_api_key()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    ids = data.get("ids") or []
    if not ids:
        return jsonify(ErrorResponse(detail="ids 不能为空").model_dump()), 400
    deleted = batch_delete_conversations(ids)
    return jsonify({"detail": f"已删除 {deleted} 个对话", "deleted": deleted}), 200


@bp.route("/api/conversations/<conversation_id>/prompt", methods=["PUT"])
@monitor_response("conversation:update_prompt")
def update_prompt_api(conversation_id: str):
    """修改提示词（用于重提）"""
    err = check_api_key()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    new_prompt = data.get("user_prompt", "").strip()
    if not new_prompt:
        return jsonify(ErrorResponse(detail="user_prompt 不能为空").model_dump()), 400

    if update_prompt(conversation_id, new_prompt):
        return jsonify({"detail": "提示词已更新", "user_prompt": new_prompt}), 200
    return jsonify(ErrorResponse(detail="对话不存在").model_dump()), 404
