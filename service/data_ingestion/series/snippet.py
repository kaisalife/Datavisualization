"""Series 注入片段生成（v4）。

把一条 SemanticSeries 编译为可直接拼入生成代码的 Python 片段：
- 相对路径解析（同目录/上级目录的 .parquet -> 构建时绝对路径回退）
- 产出全局变量 df（从该 series 的 parquet 加载），无 conn、无 duckdb
标识符加下划线前缀避免与 LLM 生成代码冲突，df 除外。
"""
from __future__ import annotations

import os

from service.data_ingestion.series.models import SemanticSeries

_SERIES_SNIPPET = '''# --- series: {series_id}（守护层注入，请勿修改本段）---
import pandas as _pd
from pathlib import Path as _P

_P_FALLBACK = _P(r"{data_path}")


def _p_resolve_series() -> _P:
    """定位 series .parquet: 同目录 -> 上级目录 -> 构建时绝对路径。"""
    here = _P(__file__).resolve().parent
    _fn = "{filename}"
    for _cand in (here / _fn, here.parent / _fn):
        if _cand.exists():
            return _cand
    return _P_FALLBACK


df = _pd.read_parquet(_p_resolve_series())
# --- end series ---
'''


def series_snippet(series: SemanticSeries) -> str:
    """生成可注入沙箱/产物的 series 读取片段（仅 df）。

    Args:
        series: 已选定的语义 series

    Returns:
        Python 代码片段文本
    """
    import posixpath

    filename = posixpath.basename(series.data_path) or "series.parquet"
    return _SERIES_SNIPPET.format(
        series_id=series.series_id,
        data_path=os.path.normpath(series.data_path),
        filename=filename,
    )