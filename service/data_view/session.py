"""数据视图会话门面：dataset_id → 表清单 / describe / run_view。

`agent_tools/tool_data_view.py`（MCP 薄适配器）与规划期本地工具共用这一层；
状态全部在磁盘（会话目录），进程重启无影响。

会话目录布局（沿用接入层约定）::

    runtime/datasets/ds_<12hex>/
    ├── manifest.json          # SeriesCatalog（identity 与 view 派生 series 都在这里）
    ├── <series_id>.parquet    # identity series 产物
    ├── raw/                   # save_raw=True 时的归一化原始表（raw_<i>.parquet）
    └── views/                 # 派生 view 产物（vw_<hash>.parquet + manifest）

对外契约（docs/数据清洗工具集/04）：

- ``describe_dataset(dataset_id)``：表清单（SQL 可引用的别名）、列/dtype、
  行数、样品、已有 view 列表——无副作用；
- ``run_view(dataset_id, spec, mode)``：执行并返回 ``view_id + schema + 样品``；
  ``materialize`` 才落盘（同一 spec 永远同一 view_id）。

表别名约定（SQL 里的 ``from`` 对象）：raw 表按 ``table_<i>``、series 按
``series_<i>`` 编号，describe 的返回给出 alias → 逻辑名映射。别名必须是
引擎认可 ``[A-Za-z0-9_]`` 标识符；业务表名/列名不进入本层逻辑。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

from service.observability import get_logger

try:  # 包导入 / 脚本直跑双写法
    from spec import DATA_VIEW_VERSION, DataViewError, INPUT_INVALID, INPUT_NOT_FOUND, spec_from_dict, spec_summary
    from engine import DataViewEngine
    from cache import list_views
except ImportError:  # pragma: no cover - 兼容直接运行
    from .spec import (  # type: ignore
        DATA_VIEW_VERSION,
        DataViewError,
        INPUT_INVALID,
        INPUT_NOT_FOUND,
        spec_from_dict,
        spec_summary,
    )
    from .engine import DataViewEngine  # type: ignore
    from .cache import list_views  # type: ignore

logger = get_logger(__name__)

# session_id 约定：ds_ + 12 位十六进制（与 /api/data-profile/export 一致）
_DATASET_ID_RE = re.compile(r"^ds_[0-9a-f]{12}$")

# 样品行数（describe 3 行、run_view 5 行）
_SAMPLE_ROWS = 3
_RESULT_SAMPLE_ROWS = 5

# 单次返回的表数量上限（防超大宽表打满 agent 上下文；列同理）
_MAX_TABLES = 20
_MAX_SAMPLE_COLUMNS = 20

_RAW_ALIAS_RE = re.compile(r"^table_(\d+)$")


def resolve_dataset_dir(dataset_id: str, datasets_root: Path | None = None) -> Path:
    """校验 dataset_id 并返回会话目录。

    Args:
        dataset_id: ``ds_<12hex>``。
        datasets_root: 覆盖根目录（测试用）；缺省用接入层 ``get_datasets_root()``。

    Returns:
        Path: 已存在的会话目录绝对路径。

    Raises:
        DataViewError: id 格式非法（``INPUT_INVALID``）或会话不存在（``INPUT_NOT_FOUND``）。
    """
    if not _DATASET_ID_RE.fullmatch(str(dataset_id or "").strip()):
        raise DataViewError(
            f"dataset_id 格式非法: {dataset_id!r}（要求 ds_<12位hex>）", INPUT_INVALID
        )
    if datasets_root is None:
        from service.data_ingestion.series_manager import get_datasets_root

        datasets_root = get_datasets_root()
    session_dir = (Path(datasets_root) / str(dataset_id).strip()).resolve()
    if not session_dir.is_dir():
        raise DataViewError(f"数据会话不存在: {dataset_id}", INPUT_NOT_FOUND)
    return session_dir


def list_dataset_tables(dataset_id: str, datasets_root: Path | None = None) -> list[dict[str, Any]]:
    """列出会话里全部可查询表（raw 优先，其次 identity series），含 alias 映射。

    raw 缺失（图表任务默认不落 raw 表）时以 series 产物作为 SQL 输入——
    identity series 本身就是 view（docs 03 §4）。只读 manifest，不加载表数据。
    """
    session_dir = resolve_dataset_dir(dataset_id, datasets_root)
    tables: list[dict[str, Any]] = []

    for item in _load_raw_manifest(session_dir):
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        if not isinstance(index, int):
            continue
        if len(tables) >= _MAX_TABLES:
            break
        tables.append(
            {
                "alias": f"table_{index}",
                "name": str(item.get("name") or f"raw_{index}"),
                "origin": "raw",
                "rows": item.get("rows", 0),
                "columns": [str(c) for c in (item.get("columns") or [])],
            }
        )

    if len(tables) >= _MAX_TABLES:
        return tables

    series_items = _load_series_summaries(session_dir)
    for n, summary in enumerate(series_items):
        if len(tables) >= _MAX_TABLES:
            break
        tables.append(
            {
                "alias": f"series_{len([t for t in tables if t['origin'] == 'series'])}",
                "name": summary["series_id"],
                "origin": "series",
                "rows": summary["rows"],
                "columns": summary["columns"],
            }
        )
    return tables


def describe_dataset(dataset_id: str, datasets_root: Path | None = None) -> dict[str, Any]:
    """describe_dataset 完整返回：表清单（含 dtype/样品）+ 已有 view 列表。"""
    session_dir = resolve_dataset_dir(dataset_id, datasets_root)
    tables: list[dict[str, Any]] = []
    for meta in list_dataset_tables(session_dir.name, datasets_root):
        column_details: list[dict[str, str]] = []
        sample: list[dict[str, Any]] = []
        try:
            df = _read_table(session_dir, meta)
            column_details = [
                {"name": str(c), "dtype": str(d)}
                for c, d in list(zip(df.columns, df.dtypes))[:_MAX_SAMPLE_COLUMNS]
            ]
            sample = _sample_records(df.head(_SAMPLE_ROWS))
            if not isinstance(meta.get("rows"), int) or int(meta["rows"]) < 0:
                meta["rows"] = int(len(df))
        except Exception as e:
            logger.warning("数据视图样品读取失败", table=meta.get("name"), error=str(e))
            column_details = [
                {"name": c, "dtype": "?"} for c in (meta.get("columns") or [])[:_MAX_SAMPLE_COLUMNS]
            ]
        tables.append({**meta, "columns": column_details, "sample": sample})

    return {
        "dataset_id": dataset_id,
        "tables": tables,
        "views": list_views(session_dir)[:_MAX_TABLES],
        "engine_version": DATA_VIEW_VERSION,
    }


def run_view(
    dataset_id: str,
    spec_data: dict[str, Any],
    mode: str = "materialize",
    datasets_root: Path | None = None,
    engine: DataViewEngine | None = None,
) -> dict[str, Any]:
    """解析 spec → 注册输入 → 执行（materialize 落盘）→ 返回结果摘要。

    Args:
        dataset_id: 数据会话 id。
        spec_data: spec JSON dict（见 ``spec_from_dict``），缺失校验在其内完成。
        mode: ``materialize``（唯一落盘 mode）或 ``preview``（内存样品）。
        datasets_root: 覆盖数据根目录（测试用）。
        engine: 覆盖默认引擎（测试注入）。

    Returns:
        dict: ``view_id`` / ``rows`` / ``schema`` / ``sample`` / ``spec_summary`` /
        ``engine_version``；materialize 附 ``parquet_path``；缓存命中附 ``cached=True``。

    Raises:
        DataViewError: 会话或别名解析、spec 校验、执行任何一层失败（错误码稳定）。
    """
    session_dir = resolve_dataset_dir(dataset_id, datasets_root)
    spec = spec_from_dict(spec_data) if isinstance(spec_data, dict) else spec_data
    engine = engine or DataViewEngine()

    alias_index = {t["alias"]: t for t in list_dataset_tables(session_dir.name, datasets_root)}
    inputs: dict[str, pd.DataFrame] = {}
    for name in spec.inputs:
        meta = alias_index.get(name)
        if meta is None:
            aliases = ", ".join(sorted(alias_index)[:12]) or "(无)"
            raise DataViewError(
                f"输入表别名不存在: {name}；可用别名: {aliases}", INPUT_NOT_FOUND
            )
        try:
            inputs[name] = _read_table(session_dir, meta)
        except Exception as e:
            raise DataViewError(
                f"输入表 {name}（{meta.get('name')}）加载失败: {e}", INPUT_INVALID
            ) from e

    result = engine.execute(spec, inputs, mode=mode, datasets_dir=str(session_dir))
    payload: dict[str, Any] = {
        "view_id": result.view_id,
        "rows": result.rows,
        "schema": [{"name": c.name, "dtype": c.dtype} for c in result.schema],
        "sample": _sample_records(result.data.head(_RESULT_SAMPLE_ROWS)),
        "spec_summary": spec_summary(spec),
        "engine_version": DATA_VIEW_VERSION,
    }
    if result.extra.get("parquet_path"):
        payload["parquet_path"] = result.extra["parquet_path"]
    if result.extra.get("cached"):
        payload["cached"] = True
    logger.info(
        "数据视图 run_view 完成", dataset_id=dataset_id, mode=mode, view_id=result.view_id,
        rows=result.rows,
    )
    return payload


# ------------------------------------------------------------------
# 内部工具
# ------------------------------------------------------------------

def _load_raw_manifest(session_dir: Path) -> list[dict[str, Any]]:
    """读 ``raw/manifest.json``（save_raw=True 的接入产物）；缺失/损坏返回空。"""
    manifest = session_dir / "raw" / "manifest.json"
    if not manifest.exists():
        return []
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("数据视图 raw manifest 解析失败", file=str(manifest), error=str(e))
        return []


def _load_series_summaries(session_dir: Path) -> list[dict[str, Any]]:
    """从 catalog manifest 取 series 摘要（series_id / 列 / 行数），用于别名映射。"""
    try:
        from service.data_ingestion.series_manager import load_catalog_from_session

        catalog = load_catalog_from_session(datasets_dir=session_dir)
    except Exception as e:  # manifest 坏了不挡 raw 表
        logger.warning("数据视图会话 series 目录加载失败", session_dir=str(session_dir), error=str(e))
        return []
    items: list[dict[str, Any]] = []
    for series in catalog.series:
        shape = (series.extra_semantics or {}).get("shape") or {}
        columns = list(series.dtype_info.keys()) or list(series.column_label_columns or [])
        items.append(
            {
                "series_id": series.series_id,
                "rows": shape.get("rows", -1),
                "columns": [str(c) for c in columns][: _MAX_SAMPLE_COLUMNS],
            }
        )
    return items


def _read_table(session_dir: Path, meta: dict[str, Any]) -> pd.DataFrame:
    """按 describe 元数据把一张表读成 DataFrame（raw 或 series 产物）。"""
    alias = str(meta.get("alias") or "")
    if meta.get("origin") == "raw":
        match = _RAW_ALIAS_RE.fullmatch(alias)
        if not match:
            raise DataViewError(f"raw 表别名无法解析: {alias}", INPUT_INVALID)
        path = session_dir / "raw" / f"raw_{match.group(1)}.parquet"
        if not path.is_file():
            raise DataViewError(f"raw 表文件缺失: {path.name}", INPUT_NOT_FOUND)
        return pd.read_parquet(path)

    from service.data_ingestion.series_manager import load_catalog_from_session

    catalog = load_catalog_from_session(datasets_dir=session_dir)
    series = catalog.by_id(str(meta.get("name") or ""))
    if series is None:
        raise DataViewError(f"series 不存在: {meta.get('name')}", INPUT_NOT_FOUND)
    path = Path(series.data_path)
    # 防路径穿越：series 数据必须落在会话目录内（先于存在性检查，防探测）
    if session_dir.resolve() not in path.resolve().parents:
        raise DataViewError("series 数据路径越界", INPUT_INVALID)
    if not path.is_file():
        raise DataViewError(f"series 数据文件缺失: {path.name}", INPUT_NOT_FOUND)
    return pd.read_parquet(path)


def _sample_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """前 N 行样品（列数截断；to_json 保证 NaN/null → null，JSON 合法）。"""
    trimmed = df.iloc[:, :_MAX_SAMPLE_COLUMNS]
    records = json.loads(trimmed.to_json(orient="records", force_ascii=False))
    return records if isinstance(records, list) else []
