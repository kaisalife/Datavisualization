"""runtime 目录清理。

按最后修改时间清理 runtime 下的临时产物（uploads / datasets / traces / charts），
供 POST /api/cleanup 手动触发，避免服务长期运行后磁盘膨胀。

清理粒度是一级条目：文件直接删除，目录整体删除（不递归挑选子文件），
这样 datasets 的会话目录、charts 的数据集目录都能被完整移除。
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

from service.observability import get_logger
from service.runtime.constants import get_charts_dir

logger = get_logger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# 单个根目录的统计字段
_EMPTY_STATS = {"removed_files": 0, "removed_dirs": 0, "bytes_freed": 0}


def get_uploads_dir() -> Path:
    """上传文件目录，可通过 TEMP_UPLOAD_DIR 覆盖（与 app.py 保持一致）。"""
    override = os.getenv("TEMP_UPLOAD_DIR", "").strip()
    if override:
        return Path(override)
    return _PROJECT_ROOT / "runtime" / "uploads"


def get_datasets_dir() -> Path:
    """数据接入会话目录，可通过 TEMP_DATASETS_DIR 覆盖（与 series_manager 保持一致）。"""
    override = os.getenv("TEMP_DATASETS_DIR", "").strip()
    if override:
        return Path(override)
    return _PROJECT_ROOT / "runtime" / "datasets"


def get_traces_dir() -> Path:
    """trace 落盘目录，可通过 TEMP_TRACES_DIR 覆盖。"""
    override = os.getenv("TEMP_TRACES_DIR", "").strip()
    if override:
        return Path(override)
    return _PROJECT_ROOT / "runtime" / "traces"


def _is_expired(path: Path, cutoff: float) -> bool:
    """判断条目是否早于 cutoff（取不到 mtime 时保守跳过）。"""
    try:
        return path.stat().st_mtime < cutoff
    except OSError:
        return False


def _remove_entry(path: Path) -> tuple[int, int, bool]:
    """删除文件或目录。

    Returns:
        (删除的文件数, 释放的字节数, 是否为目录)
    """
    is_dir = path.is_dir()

    if is_dir:
        files = 0
        size = 0
        for root, _, filenames in os.walk(path):
            for filename in filenames:
                try:
                    size += (Path(root) / filename).stat().st_size
                    files += 1
                except OSError:
                    continue
        shutil.rmtree(path, ignore_errors=True)
        return files, size, True

    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    try:
        path.unlink()
    except OSError:
        return 0, 0, False
    return 1, size, False


def _cleanup_root(root: Path, cutoff: float) -> dict:
    """清理单个根目录下超期的一级条目，返回统计信息。"""
    stats = dict(_EMPTY_STATS)
    if not root.exists():
        return stats

    for entry in root.iterdir():
        if not _is_expired(entry, cutoff):
            continue
        files, size, is_dir = _remove_entry(entry)
        stats["removed_files"] += files
        stats["bytes_freed"] += size
        if is_dir:
            stats["removed_dirs"] += 1
    return stats


def cleanup_runtime(max_age_days: int = 7) -> dict:
    """清理 runtime 下超过 max_age_days 天未修改的产物。

    Args:
        max_age_days: 保留天数；0 表示清理当前时刻之前的全部条目。

    Returns:
        统计信息，包含 removed_files / removed_dirs / bytes_freed 以及
        details（每个子目录的明细）。
    """
    max_age_days = max(0, int(max_age_days))
    cutoff = time.time() - max_age_days * 86400

    targets = {
        "uploads": get_uploads_dir(),
        "datasets": get_datasets_dir(),
        "traces": get_traces_dir(),
        "charts": get_charts_dir(),
    }

    total = dict(_EMPTY_STATS)
    details: dict[str, dict] = {}

    for name, root in targets.items():
        try:
            stats = _cleanup_root(root, cutoff)
        except Exception as e:  # 单个目录失败不影响其它目录
            logger.warning(
                "runtime_cleanup_failed",
                target=name,
                root=str(root),
                error=str(e),
                error_type=type(e).__name__,
            )
            stats = dict(_EMPTY_STATS)
        details[name] = {"path": str(root), **stats}
        for key in total:
            total[key] += stats[key]

    if any(total.values()):
        logger.info("runtime_cleaned", max_age_days=max_age_days, **total)

    return {**total, "details": details}


def prune_uploads(max_age_hours: float | None = None) -> dict:
    """删除过期的上传文件副本（服务启动 / 手动清理时调用）。

    上传文件只在任务的数据接入阶段使用；任务完成后图表靠 series parquet，
    不依赖 ``runtime/uploads`` 下的副本。因此按保留期删除是安全的：
    - 默认保留 ``UPLOAD_RETENTION_HOURS``（72 小时）；
    - <=0 表示关闭（不删除任何文件，返回全 0）；
    - 只删单文件，不动目录结构；按 mtime 判断，正在写入的新文件不会被误删。

    Returns:
        {"removed_files": int, "bytes_freed": int}
    """
    if max_age_hours is None:
        try:
            max_age_hours = float(os.getenv("UPLOAD_RETENTION_HOURS", "72"))
        except (TypeError, ValueError):
            max_age_hours = 72.0

    stats = {"removed_files": 0, "bytes_freed": 0}
    if max_age_hours <= 0:
        return stats

    root = get_uploads_dir()
    if not root.exists():
        return stats

    cutoff = time.time() - max_age_hours * 3600
    for entry in root.iterdir():
        try:
            if not entry.is_file():
                continue
            if entry.stat().st_mtime >= cutoff:
                continue
            size = entry.stat().st_size
            entry.unlink()
            stats["removed_files"] += 1
            stats["bytes_freed"] += size
        except OSError as e:
            logger.warning(
                "upload_prune_failed",
                path=str(entry),
                error=str(e),
                error_type=type(e).__name__,
            )

    if stats["removed_files"]:
        logger.info(
            "uploads_pruned",
            removed_files=stats["removed_files"],
            bytes_freed=stats["bytes_freed"],
            retention_hours=max_age_hours,
        )
    return stats
