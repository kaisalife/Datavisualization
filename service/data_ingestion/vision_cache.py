"""多模态抽表结果缓存（内容寻址）。

同一张图片/PDF（文件字节相同）、同样的 hint / 多表开关 / 页数上限 / 模型，
抽表结果可以复用：前端先「预览」再生成图表时，不会第二次调用视觉模型。

设计要点：
- 只缓存成功结果（至少一张非空表）；失败/空结果不写缓存，下次仍会重试。
- 键包含文件内容哈希、后缀、表名、hint、multi_table、页数上限、模型签名与缓存版本；
  **不含文件路径**——预览与图表各自上传的副本（UUID 前缀不同）可以共享。
- 先写 parquet，最后写 ``meta.json`` 作为完成标记；缺失/损坏一律按未命中处理。
- 默认目录 ``runtime/cache/vision``，``VISION_CACHE=0`` 关闭，
  ``VISION_CACHE_TTL_DAYS``（默认 14）控制清理。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path

import pandas as pd

from service.data_ingestion.models import RawTable
from service.observability import get_logger
from service.runtime.constants import get_vision_cache_dir

logger = get_logger(__name__)

_CACHE_VERSION = "v1"
_META_NAME = "meta.json"
_DEFAULT_TTL_DAYS = 14


def cache_enabled() -> bool:
    """``VISION_CACHE=0/false/no/off`` 时关闭（默认开启）。"""
    value = os.getenv("VISION_CACHE", "").strip().lower()
    return value not in {"0", "false", "no", "off"}


def model_signature(llm) -> str:
    """提取视觉模型客户端签名（模型名 + 端点），用于隔离不同模型的缓存。"""
    model = (
        getattr(llm, "model_name", None)
        or getattr(llm, "model", None)
        or type(llm).__name__
    )
    base_url = getattr(llm, "openai_api_base", None) or getattr(llm, "base_url", None) or ""
    return f"{type(llm).__name__}:{model}@{base_url}"


def _file_digest(path: Path) -> str:
    """文件内容 sha256（按 1MB 分块，避免大 PDF 一次读入内存）。"""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cache_key(
    path: str | Path,
    *,
    base_name: str,
    hint: str = "",
    multi_table: bool = False,
    max_pages: int = 5,
    signature: str = "",
) -> str:
    """构造内容寻址缓存键。"""
    p = Path(path)
    parts = [
        _CACHE_VERSION,
        _file_digest(p),
        p.suffix.lower(),
        str(base_name),
        (hint or "").strip(),
        "1" if multi_table else "0",
        str(int(max_pages)),
        str(signature or ""),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:32]


def load_tables(key: str, path: str | Path) -> list[RawTable] | None:
    """读取缓存；未命中或损坏时返回 None（不抛异常）。"""
    root = get_vision_cache_dir() / key
    meta_path = root / _META_NAME
    if not meta_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        tables: list[RawTable] = []
        for item in meta.get("tables") or []:
            df = pd.read_parquet(root / item["parquet"])
            source_path = str(item.get("source_path") or "").replace("{path}", str(path))
            tables.append(
                RawTable(
                    name=str(item.get("name") or "data"),
                    df=df,
                    source_kind=str(item.get("source_kind") or "document"),
                    source_path=source_path,
                    degraded=bool(item.get("degraded", False)),
                    degraded_reason=str(item.get("degraded_reason") or ""),
                )
            )
        return tables or None
    except Exception as e:
        logger.warning(
            "视觉缓存读取失败，按未命中处理",
            key=key,
            error=str(e),
            error_type=type(e).__name__,
        )
        return None


def save_tables(key: str, tables: list[RawTable], path: str | Path) -> bool:
    """写入缓存；失败只记日志，不影响主流程。"""
    if not tables:
        return False
    root = get_vision_cache_dir()
    target = root / key
    try:
        target.mkdir(parents=True, exist_ok=True)
        items = []
        for index, table in enumerate(tables):
            parquet_name = f"t{index}.parquet"
            table.df.to_parquet(target / parquet_name, index=False)
            items.append(
                {
                    "name": table.name,
                    "parquet": parquet_name,
                    "source_kind": table.source_kind,
                    # 缓存会被下一次上传的不同路径复用：存模板，读取时再替换回当前路径
                    "source_path": str(table.source_path).replace(str(path), "{path}"),
                    "degraded": bool(table.degraded),
                    "degraded_reason": table.degraded_reason,
                }
            )
        meta = {"version": _CACHE_VERSION, "created_at": time.time(), "tables": items}
        tmp_meta = target / (_META_NAME + ".tmp")
        tmp_meta.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp_meta, target / _META_NAME)
        _prune(root)
        return True
    except Exception as e:
        logger.warning(
            "视觉缓存写入失败",
            key=key,
            error=str(e),
            error_type=type(e).__name__,
        )
        return False


def _prune(root: Path, ttl_days: int | None = None) -> None:
    """按 ``meta.json`` 的修改时间清理过期缓存；没有 meta 的残留目录留 1 天。"""
    if ttl_days is None:
        try:
            ttl_days = int(os.getenv("VISION_CACHE_TTL_DAYS", str(_DEFAULT_TTL_DAYS)))
        except ValueError:
            ttl_days = _DEFAULT_TTL_DAYS
    if ttl_days <= 0:
        return
    cutoff = time.time() - ttl_days * 86400
    orphan_cutoff = time.time() - 86400
    try:
        children = list(root.iterdir())
    except OSError:
        return
    for child in children:
        if not child.is_dir():
            continue
        meta = child / _META_NAME
        try:
            if meta.exists():
                expired = meta.stat().st_mtime < cutoff
            else:
                # 可能是另一个进程正在写入，至少保留 1 天
                expired = child.stat().st_mtime < orphan_cutoff
            if expired:
                shutil.rmtree(child, ignore_errors=True)
        except OSError:
            continue
