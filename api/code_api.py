"""
代码补全 API

POST /api/complete-viz-code   可视化代码补全
"""
import asyncio
import uuid

from flask import Blueprint, request, jsonify
from Entity import CompleteVizCodeRequest, ErrorResponse
from api.common import check_api_key, get_upload_dir, get_logger


code_bp = Blueprint("code", __name__, url_prefix="/api")


@code_bp.route("/complete-viz-code", methods=["POST"])
def complete_viz_code():
    auth_error = check_api_key()
    if auth_error:
        return auth_error

    try:
        code_file_paths = []

        if request.is_json:
            data = request.get_json() or {}
            code_file_paths = data.get("code_file_paths") or []
            user_prompt = data.get("user_prompt", "")
            scientific_lib = data.get("scientific_lib")
            model_url = data.get("model_url")
            model_type = data.get("model_type")
            model_api_key = data.get("model_api_key")
        else:
            # multipart / form-data：优先上传 .py 文件
            uploaded = request.files.getlist("code_files")
            for f in uploaded:
                if not f or not f.filename:
                    continue
                save_path = get_upload_dir() / f"{uuid.uuid4().hex}_{f.filename}"
                f.save(str(save_path))
                code_file_paths.append(str(save_path))

            # 同时也支持直接传入路径列表（分号 / 换行分隔）
            paths_form = request.form.get("code_file_paths", "")
            if paths_form:
                for p in paths_form.replace("\r", "").split("\n"):
                    p = p.strip()
                    if p:
                        code_file_paths.append(p)

            user_prompt = request.form.get("user_prompt", "")
            scientific_lib = request.form.get("scientific_lib")
            model_url = request.form.get("model_url")
            model_type = request.form.get("model_type")
            model_api_key = request.form.get("model_api_key")

        if not code_file_paths:
            return jsonify(ErrorResponse(detail="code_file_paths 不能为空").dict()), 400

        req = CompleteVizCodeRequest(
            code_file_paths=code_file_paths,
            user_prompt=user_prompt,
            scientific_lib=scientific_lib,
            model_url=model_url,
            model_type=model_type,
            model_api_key=model_api_key,
        )

        # 同步执行（补全通常较短，无需异步任务队列）
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            from service.code_completer import complete_visualization_code
            result = loop.run_until_complete(complete_visualization_code(req))
        finally:
            loop.close()

        get_logger().info("code_completion_success",
                          files=len(req.code_file_paths),
                          model=req.model_type)
        return jsonify(result), 200

    except Exception as e:
        get_logger().error("code_completion_failed", error=str(e), error_type=type(e).__name__)
        return jsonify(ErrorResponse(detail=f"{type(e).__name__}: {e}").dict()), 500
