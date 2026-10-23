"""任务级指标：完成时追加 JSONL，按天汇总耗时/状态/阶段瓶颈。

定位：服务长期运行时，任务状态只存在内存（重启即丢）、明细只在 trace 文件里。
本模块在任务结束时写一条紧凑记录，提供 `/api/metrics/tasks` 的聚合视图：

- 成功率、状态分布；
- 任务总耗时 p50/p90/p95/max；
- 最慢任务 Top-N（含图表数、失败计划数）；
- 各阶段平均/ p95 耗时（规划、图表生成等），直接指出瓶颈阶段。

设计约束：
- 只追加、不改写历史；写入用进程内锁串行化（多 worker 线程）；
- 读取时按 ``days`` 过滤，容忍坏行（日志文件被截断/手改不影响接口）；
- 文件默认 ``runtime/logs/task_metrics.jsonl``，可用 ``TASK_METRICS_PATH`` 覆盖。
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_WRITE_LOCK = threading.Lock()
_TERMINAL_STATUSES = ("success", "failed", "cancelled")


def _metrics_path() -> Path:
    raw = os.getenv("TASK_METRICS_PATH", "").strip()
    path = Path(raw) if raw else Path("runtime/logs/task_metrics.jsonl")
    return path if path.is_absolute() else _PROJECT_ROOT / path


def record_task_metrics(
    *,
    task_id: str,
    status: str,
    duration_s: float,
    model: str = "",
    charts: int = 0,
    failed_plans: int = 0,
    stages: list[dict] | None = None,
) -> None:
    """追加一条任务指标（失败只写日志，不影响任务状态）。"""
    now = time.time()
    record = {
        "task_id": str(task_id or ""),
        "status": str(status or "unknown"),
        "model": str(model or ""),
        "duration_s": round(float(duration_s), 2),
        "charts": int(charts or 0),
        "failed_plans": int(failed_plans or 0),
        "stages": [
            {
                "name": str(stage.get("name") or ""),
                "label": str(stage.get("label") or ""),
                "duration_s": round(float(stage.get("duration_s") or 0), 3),
                "status": str(stage.get("status") or ""),
            }
            for stage in (stages or [])
            if isinstance(stage, dict) and stage.get("name")
        ],
        "finished_at": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
        "finished_ts": now,
    }
    path = _metrics_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with _WRITE_LOCK:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line)
    except Exception:
        # 指标是旁路能力，不能影响任务结果
        pass


def _read_records(days: float) -> list[dict]:
    path = _metrics_path()
    if not path.exists():
        return []
    cutoff = time.time() - max(0.0, float(days)) * 86400
    records: list[dict] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(item, dict):
                    continue
                timestamp = item.get("finished_ts")
                if isinstance(timestamp, (int, float)) and timestamp >= cutoff:
                    records.append(item)
    except OSError:
        return []
    return records


def _percentile(sorted_values: list[float], ratio: float) -> float:
    if not sorted_values:
        return 0.0
    index = int(round(max(0.0, min(1.0, ratio)) * (len(sorted_values) - 1)))
    return round(float(sorted_values[index]), 2)


def summarize_task_metrics(days: float = 7, slow_limit: int = 10) -> dict[str, Any]:
    """汇总最近 ``days`` 天的任务指标。

    Args:
        days: 统计窗口（天），<=0 视为 1 天
        slow_limit: 最慢任务返回条数（1–50）

    Returns:
        状态计数、成功率、耗时分位、图表总数/均值、最慢任务、阶段耗时。
    """
    days = max(1.0, float(days))
    slow_limit = max(1, min(int(slow_limit), 50))
    records = _read_records(days)

    status_counts = Counter(str(item.get("status") or "unknown") for item in records)
    durations = sorted(float(item.get("duration_s") or 0.0) for item in records)
    terminal = sum(status_counts.get(status, 0) for status in _TERMINAL_STATUSES)
    success = status_counts.get("success", 0)

    stage_durations: dict[str, list[float]] = {}
    stage_labels: dict[str, str] = {}
    for item in records:
        for stage in item.get("stages") or []:
            if not isinstance(stage, dict):
                continue
            name = str(stage.get("name") or "")
            if not name:
                continue
            try:
                value = float(stage.get("duration_s") or 0.0)
            except (TypeError, ValueError):
                continue
            stage_durations.setdefault(name, []).append(value)
            stage_labels.setdefault(name, str(stage.get("label") or name))

    stages = []
    for name, values in stage_durations.items():
        ordered = sorted(values)
        stages.append(
            {
                "name": name,
                "label": stage_labels.get(name, name),
                "count": len(ordered),
                "avg_s": round(sum(ordered) / len(ordered), 2),
                "p95_s": _percentile(ordered, 0.95),
                "max_s": round(ordered[-1], 2),
            }
        )
    stages.sort(key=lambda item: item["avg_s"], reverse=True)

    slowest = sorted(
        records, key=lambda item: float(item.get("duration_s") or 0.0), reverse=True
    )[:slow_limit]
    slowest_items = [
        {
            "task_id": item.get("task_id", ""),
            "status": item.get("status", "unknown"),
            "model": item.get("model", ""),
            "duration_s": round(float(item.get("duration_s") or 0.0), 2),
            "charts": int(item.get("charts") or 0),
            "failed_plans": int(item.get("failed_plans") or 0),
            "finished_at": item.get("finished_at", ""),
        }
        for item in slowest
    ]

    charts_total = sum(int(item.get("charts") or 0) for item in records)
    failed_total = sum(int(item.get("failed_plans") or 0) for item in records)

    return {
        "days": days,
        "tasks": len(records),
        "status": {
            status: status_counts.get(status, 0)
            for status in (*_TERMINAL_STATUSES, "running", "pending", "unknown")
        },
        "success_rate": round(success / terminal, 4) if terminal else 0.0,
        "duration_s": {
            "p50": _percentile(durations, 0.50),
            "p90": _percentile(durations, 0.90),
            "p95": _percentile(durations, 0.95),
            "max": round(durations[-1], 2) if durations else 0.0,
        },
        "charts": {
            "total": charts_total,
            "avg": round(charts_total / len(records), 2) if records else 0.0,
        },
        "failed_plans": failed_total,
        "slowest": slowest_items,
        "stages": stages,
    }
