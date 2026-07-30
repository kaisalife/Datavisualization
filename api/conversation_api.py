"""对话日志 CRUD API

以一轮对话为单位管理日志，支持前端历史对话列表和提示词修改重提。
"""

from flask import Blueprint, request, jsonify, current_app

from api.common import check_api_key
from service.conversation_store import (
    list_conversations,
    get_conversation,
    delete_conversation,
    update_prompt,
)

bp = Blueprint("conversation_api", __name__)


@bp.route("/api/conversations", methods=["GET"])
def list_conversations_api():
    """列出所有对话（分页）"""
    err = check_api_key()
    if err:
        return err

    limit = min(int(request.args.get("limit", 50)), 200)
    offset = int(request.args.get("offset", 0))

    conversations = list_conversations(limit=limit, offset=offset)
    return jsonify({"conversations": conversations, "total": len(conversations)})


@bp.route("/api/conversations/<conversation_id>", methods=["GET"])
def get_conversation_api(conversation_id: str):
    """获取单个对话详情（含完整 agent_logs）"""
    err = check_api_key()
    if err:
        return err

    conv = get_conversation(conversation_id)
    if conv is None:
        return jsonify({"detail": "对话不存在"}), 404
    return jsonify(conv)


@bp.route("/api/conversations/<conversation_id>", methods=["DELETE"])
def delete_conversation_api(conversation_id: str):
    """删除对话"""
    err = check_api_key()
    if err:
        return err

    if delete_conversation(conversation_id):
        return jsonify({"detail": "已删除"})
    return jsonify({"detail": "对话不存在"}), 404


@bp.route("/api/conversations/<conversation_id>/prompt", methods=["PUT"])
def update_prompt_api(conversation_id: str):
    """修改提示词（用于重提）"""
    err = check_api_key()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    new_prompt = data.get("user_prompt", "").strip()
    if not new_prompt:
        return jsonify({"detail": "user_prompt 不能为空"}), 400

    if update_prompt(conversation_id, new_prompt):
        return jsonify({"detail": "提示词已更新", "user_prompt": new_prompt})
    return jsonify({"detail": "对话不存在"}), 404
