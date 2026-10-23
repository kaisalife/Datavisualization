"""数据接入内存护栏（CSV/TSV/Excel）。

为什么需要：上传接口只限制文件大小（默认 50MB），但 CSV 解析成 DataFrame 后
内存会膨胀数倍，Excel 的压缩包更可能解压出上千万单元格。一次超大文件就能把
服务进程打爆，而且**截断/采样会静默改变聚合口径**（总额、均值、排行全错）。

因此这里选择显式拒绝，并给出可操作的提示（先聚合/筛选/拆分），同时允许用
环境变量调整上限：

- ``MAX_INGEST_ROWS``：单表最大行数，默认 500000；0 = 不限制
- ``MAX_INGEST_CELLS``：单表最大单元格数（行 × 列），默认 5000000；0 = 不限制

只对 CSV/TSV/Excel 生效；JSON/Parquet 仍受上传大小限制（后续如需再扩展）。
"""
from __future__ import annotations

import os

_DEFAULT_MAX_ROWS = 500_000
_DEFAULT_MAX_CELLS = 5_000_000


class DataTooLargeError(ValueError):
    """数据表超过接入上限（继承 ValueError，调用方可按参数错误处理）。"""


def _read_limit(name: str, default: int) -> int:
    """读取非负整数上限；0 表示关闭，非法值回退默认。"""
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(0, value)


def ingest_limits() -> tuple[int, int]:
    """当前生效的 (最大行数, 最大单元格数)，0 表示不限制。"""
    return (
        _read_limit("MAX_INGEST_ROWS", _DEFAULT_MAX_ROWS),
        _read_limit("MAX_INGEST_CELLS", _DEFAULT_MAX_CELLS),
    )


def effective_row_limit(columns: int) -> int:
    """按列数折算出的单表最大行数（行上限与单元格上限取更严格者）。"""
    max_rows, max_cells = ingest_limits()
    columns = max(1, int(columns))
    effective = max_rows
    if max_cells:
        cell_rows = max(1, max_cells // columns)
        effective = min(effective, cell_rows) if effective else cell_rows
    return max(0, effective)


def enforce_ingest_limits(
    rows: int,
    columns: int,
    source: str,
    *,
    rows_are_lower_bound: bool = False,
) -> None:
    """超过上限时抛 ``DataTooLargeError``（消息可直接展示给用户）。

    Args:
        rows: 表行数；CSV 流式读取时这是"至少这么多行"
        columns: 列数
        source: 文件名（用于提示）
        rows_are_lower_bound: True 时提示"超过 N 行"而不是精确值
    """
    max_rows, max_cells = ingest_limits()
    rows = max(0, int(rows))
    columns = max(1, int(columns))

    if max_rows and rows > max_rows:
        rows_text = f"超过 {max_rows} 行" if rows_are_lower_bound else f"{rows} 行"
        raise DataTooLargeError(
            f"数据文件过大：{source} {rows_text}（接入上限 {max_rows} 行）。"
            "请先在源系统按时间/维度聚合或筛选，或拆分为多个较小文件后重试；"
            "如需放宽，可调整 MAX_INGEST_ROWS（0 = 不限制）。"
        )

    cells = rows * columns
    if max_cells and cells > max_cells:
        raise DataTooLargeError(
            f"数据文件过大：{source} 约 {rows} 行 × {columns} 列 = {cells:,} 个单元格，"
            f"超过接入上限 {max_cells:,} 个单元格。"
            "请先聚合/筛选或拆分文件；如需放宽，可调整 MAX_INGEST_CELLS（0 = 不限制）。"
        )
