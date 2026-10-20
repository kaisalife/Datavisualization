"""
数据分析 API

POST /api/data-profile  上传文件并返回数据预览 + 特征画像
GET  /api/data-profile/export  按会话/系列导出 CSV（或打包 ZIP）

独立于图表生成流程，前端可单独调用以预览数据与提取特征，无需启动 LLM agent。
支持 CSV/Excel/JSON/Parquet/文档，以及图片与 PDF（走多模态视觉模型抽表，
此时会调用 LLM）。对应计划文档中的"文件处理接口（预览数据）"与"数据分析接口（数据特征提取）"。
"""
import asyncio
import io
import re
import uuid
import zipfile
from pathlib import Path
from urllib.parse import quote

import pandas as pd
from flask import Blueprint, Response, jsonify, request
from Entity import ErrorResponse
from api.common import check_api_key, get_upload_dir, monitor_response

from service.data_ingestion.series.models import SeriesCatalog
from service.data_ingestion.series_manager import get_datasets_root

data_bp = Blueprint("data", __name__, url_prefix="/api")

_SESSION_ID_RE = re.compile(r"^ds_[0-9a-f]{12}$")
_UNSAFE_NAME_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


@data_bp.route("/data-profile", methods=["POST"])
@monitor_response("data_api:profile")
def data_profile():
    """上传数据文件，返回数据预览与特征画像。

    接入 reader 生成 DataProfile，返回 schema、前 10 行预览、列统计、
    列语义角色（time/measure/dimension/agent）、推荐图表模式。
    图片 / PDF 会经视觉模型抽表（这一步会调用 LLM）。

    请求: multipart files（一个或多个数据文件，CSV/Excel/JSON/Parquet/图片/PDF）
          hint（可选）：用户分析意图，帮助多模态抽表选主表
          multi_table（可选）：1/true 时抽出图片、PDF 页面、Office 内嵌图片里的所有表
          model_url / model_api_key（可选）：多模态抽表用的模型凭证
    响应: {"profile": {...}, "file_count": N}
    """
    auth_error = check_api_key()
    if auth_error:
        return auth_error

    hint = (request.form.get("hint") or "").strip()
    multi_table = (request.form.get("multi_table") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    vision_cfg = {
        "base_url": (request.form.get("model_url") or "").strip(),
        "api_key": (request.form.get("model_api_key") or "").strip(),
    }
    if not any(vision_cfg.values()):
        vision_cfg = None
    files = request.files.getlist("files")
    saved_paths = []
    saved_names = []
    for f in files:
        if not f or not f.filename:
            continue
        save_path = get_upload_dir() / f"{uuid.uuid4().hex}_{f.filename}"
        f.save(str(save_path))
        saved_paths.append(str(save_path))
        saved_names.append(Path(f.filename).stem)

    if not saved_paths:
        return jsonify(ErrorResponse(detail="必须提供 files").model_dump()), 400

    profile = None
    try:
        from service.data_ingestion import DataSource, build_file_options, ingest, ingest_files

        async def _run():
            if len(saved_paths) > 1:
                return await ingest_files(
                    saved_paths,
                    names=saved_names,
                    hint=hint,
                    vision_cfg=vision_cfg,
                    multi_table=multi_table,
                )
            return await ingest(
                DataSource(
                    kind="file",
                    path=saved_paths[0],
                    name=saved_names[0],
                    options=build_file_options(hint, vision_cfg, multi_table),
                )
            )

        profile = asyncio.run(_run())
        result = profile.to_prompt_dict()
        session_id = Path(profile.session_dir).name if profile.session_dir else ""
        result["session_id"] = session_id
        result["exports"] = _build_exports(profile, session_id)
        return jsonify({"profile": result, "file_count": len(saved_paths)}), 200
    except Exception as e:
        return jsonify(ErrorResponse(detail=f"{type(e).__name__}: {e}").model_dump()), 500


def _build_exports(profile, session_id: str) -> list[dict]:
    """为每个 series 生成可直接下载的 CSV 链接（保留会话目录，24 小时内有效）。"""
    if not session_id or profile.series_catalog is None:
        return []
    exports = []
    for series in profile.series_catalog.series:
        exports.append(
            {
                "series_id": series.series_id,
                "name": series.name,
                "axis_kind": series.axis_kind,
                "csv_url": (
                    "/api/data-profile/export"
                    f"?session_id={quote(session_id, safe='')}"
                    f"&series_id={quote(series.series_id, safe='')}"
                ),
            }
        )
    return exports


@data_bp.route("/data-profile/export", methods=["GET"])
@monitor_response("data_api:export")
def export_series():
    """导出数据预览产生的 series。

    请求:
        session_id（必填）：``/api/data-profile`` 返回的会话 id
        series_id（可选）：只导出指定系列；不传则打包全部系列为 ZIP

    响应:
        ``text/csv``（单系列）或 ``application/zip``（全部系列）。
        CSV 使用 UTF-8 BOM，Excel 直接打开不乱码。
    """
    auth_error = check_api_key()
    if auth_error:
        return auth_error

    session_id = (request.args.get("session_id") or "").strip()
    series_id = (request.args.get("series_id") or "").strip()
    if not session_id:
        return jsonify(ErrorResponse(detail="必须提供 session_id").model_dump()), 400
    if not _SESSION_ID_RE.fullmatch(session_id):
        return jsonify(ErrorResponse(detail="session_id 格式不正确").model_dump()), 400

    session_dir = _resolve_session(session_id)
    if session_dir is None:
        return jsonify(ErrorResponse(detail="会话不存在或已过期").model_dump()), 404

    catalog = SeriesCatalog.from_manifest(str(session_dir))

    if series_id:
        series = catalog.by_id(series_id)
        if series is None:
            return jsonify(ErrorResponse(detail="系列不存在").model_dump()), 404
        df = _series_frame(series, session_dir)
        if df is None:
            return jsonify(ErrorResponse(detail="系列数据文件不存在").model_dump()), 404
        filename = f"{_UNSAFE_NAME_RE.sub('_', series_id) or 'series'}.csv"
        return Response(
            _csv_bytes(df),
            mimetype="text/csv",
            headers=_attachment_headers(filename),
        )

    if not catalog.series:
        return jsonify(ErrorResponse(detail="会话中没有可导出的系列").model_dump()), 404

    buffer = io.BytesIO()
    used: set[str] = set()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for series in catalog.series:
            df = _series_frame(series, session_dir)
            if df is None:
                continue
            base = _UNSAFE_NAME_RE.sub("_", series.series_id) or "series"
            name = base
            suffix = 1
            while name in used:
                name = f"{base}_{suffix}"
                suffix += 1
            used.add(name)
            archive.writestr(f"{name}.csv", _csv_bytes(df))

    if not used:
        return jsonify(ErrorResponse(detail="系列数据文件不存在").model_dump()), 404
    return Response(
        buffer.getvalue(),
        mimetype="application/zip",
        headers=_attachment_headers("series_export.zip", "series_export.zip"),
    )


def _resolve_session(session_id: str) -> Path | None:
    """校验 session_id 并返回会话目录（防止路径穿越）。"""
    if not _SESSION_ID_RE.fullmatch(session_id):
        return None
    root = get_datasets_root().resolve()
    session_dir = (root / session_id).resolve()
    if session_dir.parent != root or not session_dir.is_dir():
        return None
    return session_dir


def _series_frame(series, session_dir: Path) -> pd.DataFrame | None:
    """读取 series parquet；路径必须落在会话目录内。"""
    path = Path(series.data_path).resolve()
    if session_dir != path.parent and session_dir not in path.parents:
        return None
    if not path.is_file():
        return None
    return pd.read_parquet(path)


def _csv_bytes(df: pd.DataFrame) -> bytes:
    """DataFrame -> CSV 字节（带 BOM，Excel 打开中文不乱码）。"""
    return df.to_csv(index=False).encode("utf-8-sig")


def _attachment_headers(filename: str, fallback: str = "export.csv") -> dict[str, str]:
    """下载头：ASCII 兜底 + RFC 5987 UTF-8 文件名。"""
    return {
        "Content-Disposition": (
            f"attachment; filename=\"{fallback}\"; "
            f"filename*=UTF-8''{quote(filename, safe='')}"
        )
    }


@data_bp.route("/charts-dir", methods=["GET"])
@monitor_response("data_api:charts_dir")
def charts_dir():
    """返回后端固定图表目录的绝对路径，供前端"打开图表文件夹"使用。"""
    auth_error = check_api_key()
    if auth_error:
        return auth_error
    from service.runtime.constants import get_charts_dir
    return jsonify({"dir": str(get_charts_dir().resolve())}), 200
