"""Series 数据形态摘要与图表类型建议（纯函数，无 IO）。

在 series 落盘时计算一次数据形态（行数、时间点/类别数、指标数、数值范围、
是否含负值），随 manifest 持久化；规划阶段据此向 LLM 提供"这套数据适合什么图"
的确定性提示，避免所有数据都被画成柱状图。

本模块只依赖 pandas，不 import series 包内的其他模块，避免循环依赖。
"""
from __future__ import annotations

from typing import Any

import pandas as pd

# 计算数值范围时的采样上限：series 通常不大，但形态摘要不应成为大表的负担
_MAX_SAMPLE_ROWS = 5000
_MAX_LABEL_EXAMPLES = 6


def _numeric_series(df: pd.DataFrame, column: str) -> pd.Series:
    """取列的可数值化样本（无法转换的值为 NaN）。"""
    sample = df[column].head(_MAX_SAMPLE_ROWS)
    return pd.to_numeric(sample, errors="coerce").dropna()


def compute_series_shape(
    df: pd.DataFrame,
    axis_kind: str,
    row_label_column: str | None,
    column_label_columns: list[str],
) -> dict[str, Any]:
    """计算一条 series 的数据形态摘要（JSON 可序列化）。

    Args:
        df: series 的 DataFrame（行标签列已 reset 为真实列）
        axis_kind: time_series / categorical_comparison / distribution / part_to_whole / generic
        row_label_column: 行标签列（时间或类别），可为空
        column_label_columns: 指标/系列列

    Returns:
        dict，包含 rows / row_labels / measure_count / numeric_columns /
        time_like / non_negative / has_negative / value_min / value_max /
        row_label_kind / row_label_examples / summary / shape_version。
    """
    if df is None:
        df = pd.DataFrame()

    rows = int(len(df))
    columns = [str(c) for c in df.columns]
    row_label = str(row_label_column) if row_label_column else None
    if row_label and row_label in df.columns:
        try:
            row_labels = int(df[row_label].nunique(dropna=True))
        except Exception:
            row_labels = rows
        examples = [
            str(v)[:24]
            for v in df[row_label].dropna().drop_duplicates().head(_MAX_LABEL_EXAMPLES).tolist()
        ]
    else:
        row_labels = rows
        examples = []

    numeric_columns: list[str] = []
    value_min: float | None = None
    value_max: float | None = None
    has_negative = False
    has_values = False
    for col in column_label_columns:
        col = str(col)
        if col not in df.columns:
            continue
        values = _numeric_series(df, col)
        if values.empty:
            continue
        numeric_columns.append(col)
        has_values = True
        col_min = float(values.min())
        col_max = float(values.max())
        if value_min is None or col_min < value_min:
            value_min = col_min
        if value_max is None or col_max > value_max:
            value_max = col_max
        if col_min < 0:
            has_negative = True

    measure_count = len(numeric_columns) or len(column_label_columns)
    time_like = str(axis_kind or "").lower() == "time_series"
    if time_like:
        row_label_kind = "time"
    elif row_label:
        row_label_kind = "category"
    else:
        row_label_kind = "none"

    shape: dict[str, Any] = {
        "shape_version": 1,
        "rows": rows,
        "row_labels": row_labels,
        "measure_count": int(measure_count),
        "series_count": len(column_label_columns),
        "numeric_columns": numeric_columns,
        "time_like": time_like,
        "row_label_kind": row_label_kind,
        "row_label_examples": examples,
        "has_values": has_values,
        "has_negative": bool(has_negative),
        "non_negative": bool(not has_negative),
        "all_equal": bool(
            has_values and value_min is not None and value_max is not None
            and abs(value_max - value_min) < 1e-12
        ),
    }
    if value_min is not None:
        shape["value_min"] = round(value_min, 6)
    if value_max is not None:
        shape["value_max"] = round(value_max, 6)
    shape["summary"] = format_shape_summary(shape)
    return shape


def format_shape_summary(shape: dict[str, Any] | None) -> str:
    """把形态 dict 压成一行可读摘要（供 prompt / 工具输出）。"""
    if not shape:
        return ""
    n = int(shape.get("row_labels") or shape.get("rows") or 0)
    kind = shape.get("row_label_kind")
    if kind == "time":
        head = f"{n} 个时间点"
    elif kind == "category":
        head = f"{n} 个类别"
    else:
        head = f"{int(shape.get('rows') or n)} 行"

    measures = int(shape.get("measure_count") or 0)
    parts = [head]
    if measures:
        parts.append(f"{measures} 个指标")
    if shape.get("has_negative"):
        parts.append("含负值")
    return " × ".join(parts)


def suggest_chart_types(
    axis_kind: str, shape: dict[str, Any] | None
) -> tuple[list[str], list[str], str]:
    """只依据数据形态给出图表类型建议，不掺入用户意图。

    Args:
        axis_kind: semantic series 的语义类型
        shape: compute_series_shape 的结果；老 manifest 可能为空

    Returns:
        (首选类型列表, 备选类型列表, 一句话理由)，类型名为 pyecharts 常用写法。
    """
    kind = str(axis_kind or "generic").lower()
    shape = shape or {}
    n = int(shape.get("row_labels") or shape.get("rows") or 0)
    measures = int(shape.get("measure_count") or 0)
    non_negative = bool(shape.get("non_negative", True))
    time_like = kind == "time_series" or bool(shape.get("time_like"))

    if time_like:
        if n >= 3:
            return (
                ["Line", "Area"],
                ["Bar"],
                f"时间序列有 {n} 个时间点，折线/面积图才能表达连续变化趋势",
            )
        return (
            ["Bar", "Line"],
            [],
            "时间点很少（≤2），柱状对比或折线都能表达，优先按用户需求",
        )

    if kind == "distribution":
        return (
            ["Histogram", "Boxplot"],
            [],
            "单指标分布更适合直方图看形状、箱线图看异常值",
        )

    if kind == "part_to_whole":
        if non_negative and 2 <= n <= 8:
            return (
                ["Pie", "Treemap"],
                ["Bar"],
                f"{n} 个非负类别可构成整体，饼图/矩形树图用于看份额",
            )
        return (
            ["Bar", "Treemap"],
            [],
            "类别过多或含负值，不适合饼图，改用柱状对比",
        )

    if kind == "categorical_comparison":
        if non_negative and 2 <= n <= 6 and measures <= 1:
            return (
                ["Bar"],
                ["Pie", "Treemap"],
                f"{n} 个类别的单指标对比：柱状图看高低，饼图可补充构成",
            )
        if n > 12:
            alternatives = ["Treemap"]
            if measures >= 2:
                alternatives.append("Scatter")
            return (
                ["Bar"],
                alternatives,
                f"类别较多（{n} 个），柱状图按指标降序取 Top 10 + 其他最易读",
            )
        alternatives = []
        if measures >= 2:
            alternatives.append("Scatter")
        if non_negative and n <= 8:
            alternatives.append("Pie")
        return (
            ["Bar"],
            alternatives,
            f"{n} 个类别的指标对比，优先柱状图"
            + ("；多指标可另画散点看关系" if measures >= 2 else ""),
        )

    # generic：没有明确时间/维度语义，按数值列数量给保守建议
    # 单列数值且没有行标签时，本质是一组观测值，优先看分布而不是强行画类别柱状图。
    if (
        shape.get("row_label_kind") == "none"
        and shape.get("has_values")
        and measures == 1
        and n >= 5
    ):
        return (
            ["Histogram", "Boxplot"],
            ["Bar"],
            f"只有 1 个数值指标、{n} 行观测值，直方图/箱线图更适合看分布",
        )
    if measures >= 2:
        return (
            ["Scatter", "Heatmap"],
            ["Line"],
            f"有 {measures} 个数值列，散点/热力图适合看指标间关系",
        )
    if non_negative and 2 <= n <= 6:
        return (
            ["Bar"],
            ["Pie"],
            "缺少明确时间轴，按类别对比处理",
        )
    return (
        ["Bar"],
        [],
        "数据语义不明确，先用柱状图做保守展示",
    )
