"""
图表生成 API

POST /api/generate-chart-with-prompt   提交生成任务
GET  /api/chart/<chart_id>             获取图表 HTML
"""
import json
import uuid
from datetime import datetime
from pathlib import Path

from flask import Blueprint, request, jsonify, send_from_directory, current_app
from Entity import GenerateChartWithPromptRequest, ErrorResponse, OptimizeChartRequest
from api.common import (
    check_api_key, ensure_queue_capacity, get_upload_dir, get_tasks, get_tasks_lock,
    get_executor, prune_tasks, _run_service_main_in_executor, _run_optimize_in_executor,
    monitor_response,
)
from api.source_config import parse_json_object, validate_source_configs
from service.observability import get_logger
from service.runtime.conversation_store import create_conversation


logger = get_logger(__name__)

chart_bp = Blueprint("chart", __name__, url_prefix="/api")


@chart_bp.route("/generate-chart-with-prompt", methods=["POST"])
@monitor_response("chart_api:generate")
def generate_chart_with_prompt():
    auth_error = check_api_key()
    if auth_error:
        return auth_error

    # 顺手回收过期的终态任务（防任务表无限增长）
    try:
        prune_tasks()
    except Exception as e:
        logger.warning("task_prune_failed", error=str(e), error_type=type(e).__name__)

    try:
        # --- 文件上传 ---
        files = request.files.getlist("files")
        saved_paths = []
        for f in files:
            if not f or not f.filename:
                continue
            original_name = Path(f.filename).name
            if not original_name:
                continue
            save_path = get_upload_dir() / f"{uuid.uuid4().hex}_{original_name}"
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
        # 一图多表：把图片 / PDF / Office 内嵌图片里的每张表都抽出来
        multi_table = (request.form.get("multi_table") or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

        # --- 数据库源 / API 源（JSON string，共用早失败校验）---
        try:
            db_config = parse_json_object(request.form.get("db_config"), "db_config")
            api_config = parse_json_object(request.form.get("api_config"), "api_config")
            validate_source_configs(db_config, api_config)
        except ValueError as e:
            return jsonify(ErrorResponse(detail=str(e)).model_dump()), 400

        # 必须至少提供一种数据源
        if not saved_paths and not db_config and not api_config:
            return jsonify(ErrorResponse(detail="必须提供 files 或 db_config 或 api_config 其中之一").model_dump()), 400

        request_model = GenerateChartWithPromptRequest(
            file_paths=saved_paths if saved_paths else None,
            db_config=db_config,
            api_config=api_config,
            user_prompt=user_prompt,
            config=config,
            model_url=model_url,
            model_type=model_type,
            model_api_key=model_api_key,
            mcp_prompt=mcp_prompt,
            skill_prompt=skill_prompt,
            viz_mode=viz_mode,
            multi_table=multi_table,
        )

        # --- 提交任务 ---
        capacity_error = ensure_queue_capacity()
        if capacity_error:
            return capacity_error
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
                                    "raw": None, "created_at": datetime.now().isoformat()}

        # 线程池中没有 Flask 应用上下文，需传入 app 并在函数内手动推入
        app = current_app._get_current_object()
        get_executor().submit(_run_service_main_in_executor, app, task_id, request_model, conversation_id)

        return jsonify({"task_id": task_id, "status": "pending", "conversation_id": conversation_id}), 202

    except Exception as e:
        return jsonify(ErrorResponse(detail=f"{type(e).__name__}: {e}").model_dump()), 500


@chart_bp.route("/optimize-chart", methods=["POST"])
@monitor_response("chart_api:optimize")
def optimize_chart():
    """单图二次优化：基于已生成的图表资产，只跑优化 agent（不重跑 pipeline）。

    表单字段：
    - chart_id: 被优化的 HTML 文件名（前端资产卡提供）
    - user_prompt: 优化指令（改标题/配色/只显示 Top5…）
    - model_url / model_type / model_api_key: 同生成接口
    """
    auth_error = check_api_key()
    if auth_error:
        return auth_error

    try:
        prune_tasks()
    except Exception as e:
        logger.warning("task_prune_failed", error=str(e), error_type=type(e).__name__)

    try:
        chart_id = (request.form.get("chart_id") or "").strip()
        user_prompt = (request.form.get("user_prompt") or "").strip()

        # chart_id 只允许是文件名（与 /api/chart/<chart_id> 同样的穿越校验）
        if not chart_id or "/" in chart_id or "\\" in chart_id or ".." in chart_id:
            return jsonify(ErrorResponse(detail="Invalid chart ID").model_dump()), 400
        if not user_prompt:
            return jsonify(ErrorResponse(detail="user_prompt 不能为空").model_dump()), 400

        # 资产必须真实存在（早失败：缺 plan/series/代码时还没建任务就报错）
        from service.runtime.chart_assets import find_asset_by_chart_id

        asset = find_asset_by_chart_id(chart_id)
        if asset is None:
            return jsonify(ErrorResponse(detail=f"未找到可优化的图表: {chart_id}").model_dump()), 404

        request_model = OptimizeChartRequest(
            chart_id=chart_id,
            user_prompt=user_prompt,
            config=request.form.get("config"),
            model_url=request.form.get("model_url"),
            model_type=request.form.get("model_type"),
            model_api_key=request.form.get("model_api_key"),
        )

        # --- 提交任务 ---
        capacity_error = ensure_queue_capacity()
        if capacity_error:
            return capacity_error
        task_id = uuid.uuid4().hex
        conversation_id = create_conversation(
            user_prompt=f"[优化 {chart_id}] {user_prompt}",
            viz_mode="optimize",
            task_id=task_id,
        )
        with get_tasks_lock():
            get_tasks()[task_id] = {
                "status": "pending", "result": None, "error": None,
                "raw": None, "created_at": datetime.now().isoformat(),
            }

        app = current_app._get_current_object()
        get_executor().submit(_run_optimize_in_executor, app, task_id, request_model, conversation_id)

        return jsonify({"task_id": task_id, "status": "pending", "conversation_id": conversation_id}), 202

    except Exception as e:
        return jsonify(ErrorResponse(detail=f"{type(e).__name__}: {e}").model_dump()), 500


@chart_bp.route("/task-assets/<task_id>", methods=["GET"])
@monitor_response("chart_api:task_assets")
def task_assets(task_id):
    """任务资产清单：该任务产出的图表卡片（供前端资产管理与二次优化选图）。

    数据从 assets.json 按 task_id 过滤；旧任务（登记机制之前的）从任务 raw
    结果现场合成兜底。任意时刻可只读调用。
    """
    auth_error = check_api_key()
    if auth_error:
        return auth_error

    if not task_id:
        return jsonify(ErrorResponse(detail="Invalid task ID").model_dump()), 400

    with get_tasks_lock():
        task = get_tasks().get(task_id)
    if task is None:
        return jsonify(ErrorResponse(detail=f"Task not found: {task_id}").model_dump()), 404

    from service.runtime.chart_assets import asset_card, find_task_assets

    cards = find_task_assets(task_id)
    if not cards:
        # 兜底：登记机制之前的任务，从 raw 结果合成
        raw = task.get("raw") or {}
        for item in raw.get("successful_charts", []):
            plan = item.get("plan") or {}
            chart_name = Path(item.get("chart_path") or "").name
            if not chart_name:
                continue
            cards.append(asset_card({
                "chart_id": chart_name,
                "plan_id": plan.get("plan_id", ""),
                "plan_name": plan.get("plan_name", ""),
                "chart_title": plan.get("chart_title", ""),
                "chart_type": plan.get("chart_type", ""),
                "version": 0,
            }))

    return jsonify({"task_id": task_id, "assets": cards})


@chart_bp.route("/chart/<chart_id>", methods=["GET"])
@monitor_response("chart_api:get_chart")
def get_chart(chart_id):
    auth_error = check_api_key()
    if auth_error:
        return auth_error

    # 安全校验：防止路径穿越
    if not chart_id or "/" in chart_id or "\\" in chart_id or ".." in chart_id:
        return jsonify(ErrorResponse(detail="Invalid chart ID").model_dump()), 400

    charts_dir = get_charts_dir()
    if not charts_dir.exists():
        return jsonify(ErrorResponse(detail="Charts directory not found").model_dump()), 404

    candidate = charts_dir / chart_id
    if not candidate.exists():
        # fallback：在 charts 目录下递归找（兼容旧路径结构：charts/文件名/charts/*.html）
        for p in charts_dir.rglob(chart_id):
            candidate = p
            break
        else:
            return jsonify(ErrorResponse(detail="Chart not found").model_dump()), 404

    try:
        return send_from_directory(str(candidate.parent), candidate.name)
    except Exception as e:
        return jsonify(ErrorResponse(detail=f"{type(e).__name__}: {e}").model_dump()), 500


def get_charts_dir() -> Path:
    from api.common import get_charts_dir as _get
    return _get()
