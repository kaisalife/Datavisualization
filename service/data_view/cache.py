"""数据视图缓存：view_id -> parquet + manifest 落盘与命中。

物化位置约定：``<datasets_dir>/views/<view_id>.parquet``，
manifest 同名 ``.manifest.json`` 记录 spec payload、输入指纹、引擎/插件版本、
行数与列 schema——图表 HTML 的数值必须与这份 parquet 一致（05 的真机验收口径）。

失败绝不落盘（engine 已保证执行失败不进到这里）；数据变更（指纹不同）
自动得到新 view_id，旧产物不受影响——「不可变产物」原则天然成立。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from service.observability import get_logger

try:  # 包导入 / 脚本直跑双写法
    from spec import DataViewError, INPUT_INVALID, payload_of, spec_summary
except ImportError:  # pragma: no cover - 兼容直接运行
    from .spec import DataViewError, INPUT_INVALID, payload_of, spec_summary  # type: ignore

if TYPE_CHECKING:  # 仅类型提示，避免引擎 与 缓存 的循环依赖
    from engine import DataViewResult

logger = get_logger(__name__)


def views_dir(datasets_dir: str | Path) -> Path:
    """会话目录下的 views 子目录。"""
    return Path(datasets_dir) / "views"


def materialize_view(
    spec,
    result: DataViewResult,
    datasets_dir: str | Path,
    registry: PluginRegistry | None = None,
) -> str:
    """把一次执行结果物化到磁盘，返回 parquet 绝对路径。

    Args:
        spec: 原始 ViewSpec（进 manifest 做审计）。
        result: engine.execute 的产物。
        datasets_dir: 数据会话目录（``runtime/datasets/<ds_id>``）。
        registry: 未使用（保留形参保持签名稳定；插件版本已在 manifest 里）。

    Returns:
        str: parquet 绝对路径（posix 风格）。

    Raises:
        DataViewError: datasets_dir 非法或写盘失败。
    """
    directory = Path(datasets_dir)
    if not directory.is_dir():
        raise DataViewError(f"datasets_dir 不存在: {directory}", INPUT_INVALID)
    out_dir = views_dir(directory)
    out_dir.mkdir(parents=True, exist_ok=True)

    parquet = out_dir / f"{result.view_id}.parquet"
    manifest_path = out_dir / f"{result.view_id}.manifest.json"
    # 同 id 幂等：内容寻址保证同 id 同数据，重复物化直接复用
    if parquet.exists() and manifest_path.exists():
        logger.info("数据视图缓存命中", view_id=result.view_id, rows=result.rows)
        result.extra["cached"] = True
        return parquet.absolute().as_posix()

    try:
        result.data.to_parquet(parquet, index=False)
        manifest = {
            "view_id": result.view_id,
            "spec": payload_of(spec),
            "spec_summary": spec_summary(spec),
            "inputs_fingerprints": result.inputs_fingerprints,
            "engine_version": result.extra.get("engine_version"),
            "plugin_version": result.plugin_version,
            "rows": result.rows,
            "columns": [
                {"name": c.name, "dtype": c.dtype} for c in result.schema
            ],
            "parquet": parquet.name,
            "created_at": time.time(),
        }
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        # 写盘失败清理半成品，避免下次命中残缺缓存
        for p in (parquet, manifest_path):
            if p.exists():
                p.unlink(missing_ok=True)
        raise DataViewError(f"数据视图物化失败: {e}", INPUT_INVALID) from e

    logger.info(
        "数据视图已物化", view_id=result.view_id, rows=result.rows, file=str(parquet)
    )
    return parquet.absolute().as_posix()


def load_cached(datasets_dir: str | Path, view_id: str) -> Path | None:
    """按 view_id 查缓存；parquet 与 manifest 同时存在才算命中。"""
    if not str(view_id or "").strip():
        return None
    directory = Path(datasets_dir) / "views"
    parquet = directory / f"{view_id}.parquet"
    manifest = directory / f"{view_id}.manifest.json"
    return parquet if parquet.exists() and manifest.exists() else None


def list_views(datasets_dir: str | Path) -> list[dict[str, Any]]:
    """列出会话目录下全部 view 的摘要（describe_dataset / 预览响应用）。"""
    directory = views_dir(datasets_dir)
    if not directory.is_dir():
        return []
    items: list[dict] = []
    for manifest_path in sorted(directory.glob("*.manifest.json")):
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        items.append(
            {
                "view_id": data.get("view_id", manifest_path.stem.removesuffix(".manifest")),
                "spec_summary": data.get("spec_summary", ""),
                "rows": data.get("rows"),
                "columns": [c.get("name") for c in data.get("columns", [])],
            }
        )
    return items