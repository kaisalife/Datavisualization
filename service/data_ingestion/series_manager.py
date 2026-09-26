"""Series 会话管理（v4）。

每个数据接入会话使用一个独立会话目录（内含 manifest.json + 各 series .parquet），
不再使用 DuckDB。取代旧的 duckdb_manager.py。

核心职责:
- 分配会话目录（runtime/datasets/ds_<sid>/）
- 定期清理过期会话目录（按 manifest.json 的修改时间）
- 从会话目录加载 SeriesCatalog
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from service.data_ingestion.series.models import SeriesCatalog
from service.observability import get_logger


logger = get_logger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# manifest 若不存在也视为会话痕迹（目录内有 .parquet 也算），用于清理判定
SESSION_MARKERS = ("manifest.json",)


def get_datasets_root() -> Path:
    """获取会话数据集根目录，可通过环境变量 TEMP_DATASETS_DIR 覆盖。

    Returns:
        会话根目录（保留旧 _get_temp_root 行为）。
    """
    override = os.getenv("TEMP_DATASETS_DIR")
    if override:
        return Path(override)
    return PROJECT_ROOT / "runtime" / "datasets"


def allocate_session_dir(session_id: str | None = None) -> tuple[str, Path]:
    """分配一个会话目录。返回 (session_id, dir)。

    每次调用时顺带清理超过 max_age_hours 的旧会话目录。
    """
    sid = session_id or f"ds_{uuid.uuid4().hex[:12]}"
    path = get_datasets_root() / sid
    path.mkdir(parents=True, exist_ok=True)
    cleanup_old_session_dirs()
    return sid, path


def _is_session_dir(d: Path) -> bool:
    """判定一个子目录是否为 series 会话目录（存在 manifest 或 .parquet。）"""
    if (d / "manifest.json").exists():
        return True
    if any(p.suffix == ".parquet" for p in d.glob("*.parquet")):
        return True
    return False


def cleanup_old_session_dirs(max_age_hours: float = 24.0) -> int:
    """清理超过 max_age_hours 的旧系列会话目录。

    Series 文件在会话结束后不再需要，定期清理避免磁盘膨胀。
    按 manifest.json（或目录内 .parquet）的修改时间判定会话年龄。

    Returns:
        清理的目录数
    """
    import time

    t0 = time.perf_counter()
    datasets_root = get_datasets_root()
    if not datasets_root.exists():
        return 0

    now = time.time()
    max_age_seconds = max_age_hours * 3600
    cleaned = 0
    scanned = 0

    for session_dir in datasets_root.iterdir():
        if not session_dir.is_dir():
            continue
        if not _is_session_dir(session_dir):
            continue

        scanned += 1

        # 用 manifest 或第一个 .parquet 的 mtime 作为会话时间戳
        marker = session_dir / "manifest.json"
        if not marker.exists():
            parquets = sorted(session_dir.glob("*.parquet"))
            marker = parquets[0] if parquets else None
        if marker is None:
            continue

        try:
            mtime = marker.stat().st_mtime
        except OSError:
            continue

        if (now - mtime) > max_age_seconds:
            try:
                import shutil

                shutil.rmtree(session_dir, ignore_errors=True)
                cleaned += 1
                logger.info(
                    "cleanup 删除会话目录",
                    session_dir=session_dir.name,
                    age_hours=(now - mtime) / 3600,
                )
            except OSError as e:
                logger.warning(
                    "cleanup 删除失败",
                    session_dir=session_dir.name,
                    error=str(e),
                )

    t_total = time.perf_counter() - t0
    if cleaned > 0:
        logger.info(
            "cleanup 完成",
            scanned=scanned,
            cleaned=cleaned,
            total_time_s=t_total,
            max_age_hours=max_age_hours,
        )
    else:
        logger.info("cleanup 完成", scanned=scanned, cleaned=0, total_time_s=t_total)

    return cleaned


def load_catalog_from_session(session_id: str | None = None, datasets_dir: Path | None = None) -> SeriesCatalog:
    """从会话目录加载 SeriesCatalog（供下游 chart_generator/工具解析 series_id）。

    Args:
        session_id: 会话 id（形如 ds_xxx），与 datasets_dir 二选一
        datasets_dir: 会话目录，与 session_id 二选一

    Returns:
        SeriesCatalog；目录或 manifest 不完整时返回空目录。
    """
    if datasets_dir is not None:
        return SeriesCatalog.from_manifest(str(datasets_dir))
    if session_id:
        return SeriesCatalog.from_manifest(str(get_datasets_root() / session_id))
    return SeriesCatalog(datasets_dir=str(get_datasets_root()))