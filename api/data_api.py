"""
数据分析 API

POST /api/data-profile  上传文件并返回数据预览 + 特征画像

独立于图表生成流程，前端可单独调用以预览数据与提取特征，无需启动 LLM agent。
对应计划文档中的"文件处理接口（预览数据）"与"数据分析接口（数据特征提取）"。
"""
import asyncio
import uuid
from pathlib import Path

from flask import Blueprint, request, jsonify
from Entity import ErrorResponse
from api.common import check_api_key, get_upload_dir, monitor_response


data_bp = Blueprint("data", __name__, url_prefix="/api")


@data_bp.route("/data-profile", methods=["POST"])
@monitor_response("data_api:profile")
def data_profile():
    """上传数据文件，返回数据预览与特征画像。

    接入 DuckDB 生成 DataProfile（不调用 LLM），返回 schema、前 10 行预览、
    列统计、列语义角色（time/measure/dimension/id）、推荐图表模式
    （time_series/categorical_comparison）。

    请求: multipart files（一个或多个数据文件，CSV/Excel/JSON/Parquet 等）
    响应: {"profile": {...}, "file_count": N}
    """
    auth_error = check_api_key()
    if auth_error:
        return auth_error

    files = request.files.getlist("files")
    saved_paths = []
    for f in files:
        if not f or not f.filename:
            continue
        save_path = get_upload_dir() / f"{uuid.uuid4().hex}_{f.filename}"
        f.save(str(save_path))
        saved_paths.append(str(save_path))

    if not saved_paths:
        return jsonify(ErrorResponse(detail="必须提供 files").model_dump()), 400

    profile = None
    try:
        from service.data_ingestion import ingest, ingest_files, DataSource

        async def _run():
            if len(saved_paths) > 1:
                return await ingest_files(saved_paths)
            return await ingest(DataSource(kind="file", path=saved_paths[0]))

        profile = asyncio.run(_run())
        result = profile.to_prompt_dict()
        return jsonify({"profile": result, "file_count": len(saved_paths)}), 200
    except Exception as e:
        return jsonify(ErrorResponse(detail=f"{type(e).__name__}: {e}").model_dump()), 500
    finally:
        _cleanup_duckdb(profile)


@data_bp.route("/charts-dir", methods=["GET"])
@monitor_response("data_api:charts_dir")
def charts_dir():
    """返回后端固定图表目录的绝对路径，供前端"打开图表文件夹"使用。"""
    auth_error = check_api_key()
    if auth_error:
        return auth_error
    from service.runtime.constants import get_charts_dir
    return jsonify({"dir": str(get_charts_dir().resolve())}), 200


def _cleanup_duckdb(profile) -> None:
    """删除预览产生的临时 .duckdb 文件及其空目录（预览无需保留）。"""
    if profile is None:
        return
    try:
        duckdb_path = getattr(profile, "duckdb_path", None)
        if not duckdb_path:
            return
        p = Path(duckdb_path)
        if p.exists():
            p.unlink(missing_ok=True)
        wal = p.with_suffix(".duckdb.wal")
        if wal.exists():
            wal.unlink(missing_ok=True)
        if p.parent.exists() and not any(p.parent.iterdir()):
            p.parent.rmdir()
    except Exception:
        pass
