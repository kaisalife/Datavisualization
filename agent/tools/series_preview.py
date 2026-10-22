"""series 预览的上下文保护：列很多时只展示少量列。

车间设备/传感器宽表可能有上千列。规划/debug agent 只需要确认列名、时间轴和取值，
不需要把全部列塞进上下文；这里统一截断预览列，并给出明确的“共 N 列”提示。
"""
from __future__ import annotations

import json
from typing import Any, Iterable

DEFAULT_PREVIEW_COLUMNS = 20


def compact_columns(
    columns: Iterable[Any], *, max_columns: int = DEFAULT_PREVIEW_COLUMNS
) -> str:
    """把列名列表压成一行；超过上限时保留前 N 个并标注总数。"""
    if columns is None:
        items: list[str] = []
    else:
        items = [str(item) for item in columns]
    if len(items) <= max_columns:
        return json.dumps(items, ensure_ascii=False)
    shown = json.dumps(items[:max_columns], ensure_ascii=False)
    return f"{shown[:-1]}, …]（共 {len(items)} 列）"


def compact_frame(
    df,
    *,
    row_label_column: str | None = None,
    max_columns: int = DEFAULT_PREVIEW_COLUMNS,
):
    """返回 (截断后的 DataFrame, 提示文本)。

    行标签列优先保留；其余列按原顺序取前 N-1 个。列数未超限时提示为空。
    """
    columns = list(df.columns)
    if len(columns) <= max_columns:
        return df, ""

    keep: list[str] = []
    if row_label_column and row_label_column in columns:
        keep.append(row_label_column)
    for column in columns:
        if column in keep:
            continue
        if len(keep) >= max_columns:
            break
        keep.append(column)

    note = (
        f"（数据共 {len(columns)} 列，预览只展示其中 {len(keep)} 列；"
        "图表应按业务重要性选 Top-N，而不是一次画完全部列）"
    )
    return df.loc[:, keep], note
