"""图表数据检查（纯函数，无 IO）。

在 pyecharts 真正落盘前读取 ``chart.options``，统计每个 series 的数据点数量、
空值数量和数值型数量。沙箱把摘要通过 stdout 标记回传给父进程，生成阶段据此
把"图表能渲染但数据为空/全为 0"的情况当作可修复失败或警告，而不是静默成功。

这里不做业务正确性判断（例如数值是否等于原始表），只做确定性的空数据守卫。
"""
from __future__ import annotations

import math
from typing import Any, Iterator

STATS_PREFIX = "__CHART_DATA_STATS__"


def _is_missing(value: Any) -> bool:
    """None / NaN / 空字符串视为空值；0 是有效数值。"""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, float):
        return math.isnan(value)
    return False


def _iter_values(value: Any) -> Iterator[Any]:
    """展开 series data 中的嵌套结构，取出真正的取值。"""
    if isinstance(value, dict):
        if "value" in value:
            yield from _iter_values(value["value"])
        else:
            for key, item in value.items():
                # children/links 等也是图表内容的一部分
                if key in {"children", "links"}:
                    yield from _iter_values(item)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_values(item)
        return
    yield value


def _point_is_empty(point: Any) -> bool:
    """一个数据点是否为空（标量 / 字典 / 数组都按叶子值判断）。"""
    leaves = list(_iter_values(point))
    return bool(leaves) and all(_is_missing(leaf) for leaf in leaves)


def summarize_chart_options(options: dict[str, Any] | None) -> dict[str, Any]:
    """把 pyecharts options 压成可 JSON 序列化的数据摘要。"""
    options = options if isinstance(options, dict) else {}
    series = options.get("series")
    if isinstance(series, dict):
        series = [series]
    if not isinstance(series, list):
        series = []

    summary = {
        "series_count": 0,
        "types": [],
        "total_points": 0,
        "empty_points": 0,
        "numeric_values": 0,
        "zero_values": 0,
        "has_dataset": bool(options.get("dataset")),
        "series": [],
    }
    for node in series:
        if not isinstance(node, dict):
            continue
        chart_type = str(node.get("type") or "")
        data = node.get("data")
        points = data if isinstance(data, list) else ([] if data is None else [data])
        empty_points = sum(1 for point in points if _point_is_empty(point))
        leaves = []
        for point in points:
            leaves.extend(_iter_values(point))
        numeric_values = [
            value for value in leaves
            if isinstance(value, (int, float)) and not isinstance(value, bool)
            and not _is_missing(value)
        ]
        zero_values = [value for value in numeric_values if value == 0]
        summary["series_count"] += 1
        summary["types"].append(chart_type)
        summary["total_points"] += len(points)
        summary["empty_points"] += empty_points
        summary["numeric_values"] += len(numeric_values)
        summary["zero_values"] += len(zero_values)
        summary["series"].append({
            "type": chart_type,
            "name": str(node.get("name") or ""),
            "points": len(points),
            "empty_points": empty_points,
            "numeric_values": len(numeric_values),
            "zero_values": len(zero_values),
        })
    return summary


def chart_data_issues(summary: dict[str, Any] | None) -> list[dict[str, Any]]:
    """根据数据摘要给出问题列表（severity=error/warning）。

    使用 ``dataset`` 的图表不在本函数判断范围内，避免把合法的 dataset 图表误判为空。
    """
    if not isinstance(summary, dict) or summary.get("has_dataset"):
        return []
    if int(summary.get("series_count") or 0) == 0:
        return [{
            "code": "CHART_DATA_EMPTY",
            "severity": "error",
            "message": "图表没有 series，无法确认数据已写入",
        }]

    total = int(summary.get("total_points") or 0)
    empty = int(summary.get("empty_points") or 0)
    numeric = int(summary.get("numeric_values") or 0)
    zero = int(summary.get("zero_values") or 0)
    issues: list[dict[str, Any]] = []

    if total <= 0:
        issues.append({
            "code": "CHART_DATA_EMPTY",
            "severity": "error",
            "message": "图表 series 没有数据点",
        })
        return issues
    if empty >= total:
        issues.append({
            "code": "CHART_DATA_ALL_NULL",
            "severity": "error",
            "message": f"图表 {total} 个数据点全部为空值",
        })
        return issues
    if empty / total >= 0.5:
        issues.append({
            "code": "CHART_DATA_MOSTLY_EMPTY",
            "severity": "warning",
            "message": f"图表有 {empty}/{total} 个数据点为空，图形可能不完整",
        })
    if numeric > 0 and zero >= numeric:
        issues.append({
            "code": "CHART_DATA_ALL_ZERO",
            "severity": "warning",
            "message": "图表所有数值都是 0，请确认数据筛选或聚合是否正确",
        })
    return issues
