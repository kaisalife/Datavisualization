"""
图表生成 API

POST /api/generate-chart-with-prompt   提交生成任务
GET  /api/chart/<chart_id>             获取图表 HTML
"""
import json
import uuid
from pathlib import Path

from flask import Blueprint, request, jsonify, send_from_directory
from Entity import GenerateChartWithPromptRequest, ErrorResponse
from api.common import check_api_key, get_upload_dir, get_tasks, get_tasks_lock, get_executor, _run_service_main_in_executor
from service.conversation_store import create_conversation


chart_bp = Blueprint("chart", __name__, url_prefix="/api")


@chart_bp.route("/generate-chart-with-prompt", methods=["POST"])
def generate_chart_with_prompt():
    auth_error = check_api_key()
    if auth_error:
        return auth_error

    try:
        # --- 文件上传 ---
        files = request.files.getlist("files")
        saved_paths = []
        for f in files:
            if not f or not f.filename:
                continue
            save_path = get_upload_dir() / f"{uuid.uuid4().hex}_{f.filename}"
            f.save(str(save_path))
            saved_paths.append(str(save_path))

        # --- 表单参数 ---
        user_prompt = request.form.get("user_prompt", "")
        config = request.form.get("config")
        model_url = request.form.get("model_url")
        model_type = request.form.get("model_type")
        model_api_key = request.form.get("model_api_key")
        mcp_prompt = request.form.get("mcp_prompt", "")
        skill_prompt = request.form.get("skill_prompt", "")
        viz_mode = request.form.get("viz_mode", "auto")

        # --- 数据库源（JSON string）---
        db_config = None
        db_config_str = request.form.get("db_config")
        if db_config_str:
            try:
                db_config = json.loads(db_config_str)
            except Exception as e:
                return jsonify(ErrorResponse(detail=f"db_config JSON 解析失败: {e}").dict()), 400

        # 必须至少提供一种数据源
        if not saved_paths and not db_config:
            return jsonify(ErrorResponse(detail="必须提供 files 或 db_config 其中之一").dict()), 400

        request_model = GenerateChartWithPromptRequest(
            file_paths=saved_paths if saved_paths else None,
            db_config=db_config,
            user_prompt=user_prompt,
            config=config,
            model_url=model_url,
            model_type=model_type,
            model_api_key=model_api_key,
            mcp_prompt=mcp_prompt,
            skill_prompt=skill_prompt,
            viz_mode=viz_mode,
        )

        # --- 提交任务 ---
        task_id = uuid.uuid4().hex
        # 创建对话记录
        file_paths_str = [f.filename for f in files] if files else []
        db_config_json = json.dumps(db_config, ensure_ascii=False) if db_config else None
        conversation_id = create_conversation(
            user_prompt=user_prompt,
            file_paths=file_paths_str,
            viz_mode=viz_mode,
            db_config=db_config_json,
            task_id=task_id,
        )
        with get_tasks_lock():
            get_tasks()[task_id] = {"status": "pending", "result": None, "error": None,
                                    "raw": None, "created_at": get_executor()._thread_name_prefix}

        get_executor().submit(_run_service_main_in_executor, task_id, request_model, conversation_id)

        return jsonify({"task_id": task_id, "status": "pending", "conversation_id": conversation_id}), 202

    except Exception as e:
        return jsonify(ErrorResponse(detail=f"{type(e).__name__}: {e}").dict()), 500


@chart_bp.route("/chart/<chart_id>", methods=["GET"])
def get_chart(chart_id):
    auth_error = check_api_key()
    if auth_error:
        return auth_error

    # 安全校验：防止路径穿越
    if not chart_id or "/" in chart_id or "\\" in chart_id or ".." in chart_id:
        return jsonify(ErrorResponse(detail="Invalid chart ID").dict()), 400

    charts_dir = get_charts_dir()
    if not charts_dir.exists():
        return jsonify(ErrorResponse(detail="Charts directory not found").dict()), 404

    candidate = charts_dir / chart_id
    if not candidate.exists():
        # fallback：在 charts 目录下递归找（兼容旧路径结构：charts/文件名/charts/*.html）
        for p in charts_dir.rglob(chart_id):
            candidate = p
            break
        else:
            return jsonify(ErrorResponse(detail="Chart not found").dict()), 404

    try:
        return send_from_directory(str(candidate.parent), candidate.name)
    except Exception as e:
        return jsonify(ErrorResponse(detail=f"{type(e).__name__}: {e}").dict()), 500


def get_charts_dir() -> Path:
    from api.common import get_charts_dir as _get
    return _get()
