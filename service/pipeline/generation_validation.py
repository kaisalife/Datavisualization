"""生成阶段校验报告（ValidationReport）与 GenerationResult。

对应 docs/论文参考与系统设计.md 的 D5：
- 代码执行失败时，把报错归类成稳定错误码，供 debug/前端/统计使用；
- HTML 落盘后再做一次产物校验（存在、非空、包含 ECharts 容器）；
- 每次生成尝试都产出可序列化的 generation 结果，写回 plan 并落盘到 plans/。

本模块只做确定性判断，不调用 LLM，也不修改用户原始数据。
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from service.observability import get_logger

logger = get_logger(__name__)

# 错误码 -> 给 debug/用户的处理建议
_ERROR_HINTS = {
    "CODE_SYNTAX": "检查括号、缩进、字符串引号与 Python 语法",
    "CODE_NAME_ERROR": "检查变量/函数名是否拼错，选项类是否带 opts. 前缀",
    "CODE_IMPORT_ERROR": "只允许使用项目已安装的库，禁止引入未安装依赖",
    "CODE_TYPE_ERROR": "检查 add_yaxis 等 API 的参数类型与顺序",
    "CODE_FIELD_NOT_FOUND": "用 read_series_sample 确认真实列名，禁止臆造字段",
    "CODE_DATA_ERROR": "检查空数据、缺失值、类型转换和索引越界",
    "CODE_TIMEOUT": "减少数据量或拆分图表，避免沙箱执行超时",
    "CODE_SECURITY_REJECTED": "移除文件写入/网络/危险调用；这是不可自动修复的静态拒绝",
    "CODE_HTML_MISSING": "确认代码调用了 render()，且 pyecharts 图表对象正确",
    "CODE_HTML_INVALID": "确认 render 产物是完整 HTML，包含 ECharts 容器",
    "CODE_RUNTIME_ERROR": "查看完整 traceback，定位失败步骤后修复",
}

_ERROR_PATTERNS = (
    ("CODE_SECURITY_REJECTED", re.compile(r"安全检查失败|安全校验|forbidden|not allowed", re.I)),
    ("CODE_TIMEOUT", re.compile(r"timeout|timed out|超时", re.I)),
    ("CODE_SYNTAX", re.compile(r"SyntaxError|IndentationError|TabError")),
    ("CODE_NAME_ERROR", re.compile(r"NameError")),
    ("CODE_IMPORT_ERROR", re.compile(r"ModuleNotFoundError|ImportError")),
    ("CODE_FIELD_NOT_FOUND", re.compile(r"KeyError|字段.*不存在|column.*not found", re.I)),
    ("CODE_TYPE_ERROR", re.compile(r"TypeError")),
    ("CODE_HTML_MISSING", re.compile(r"HTML 未生成或为空|未调用 render", re.I)),
    ("CODE_DATA_ERROR", re.compile(r"ValueError|IndexError|EmptyDataError|数据为空", re.I)),
)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def new_report(*, stage: str = "runtime", attempt: int = 1) -> dict[str, Any]:
    """创建空校验报告。"""
    return {
        "ok": True,
        "stage": stage,
        "attempt": max(1, int(attempt)),
        "checked_at": _now(),
        "errors": [],
        "warnings": [],
    }


def add_error(
    report: dict,
    code: str,
    message: str,
    *,
    hint: str = "",
    repairable: bool = True,
    **extra: Any,
) -> dict:
    """向报告追加一个错误项。"""
    report.setdefault("errors", []).append({
        "code": code,
        "message": str(message),
        "hint": hint or _ERROR_HINTS.get(code, ""),
        "repairable": bool(repairable),
        **extra,
    })
    report["ok"] = False
    return report


def add_warning(report: dict, code: str, message: str, **extra: Any) -> dict:
    """向报告追加一个警告项（不改变 ok）。"""
    report.setdefault("warnings", []).append({
        "code": code,
        "message": str(message),
        **extra,
    })
    return report


def classify_runtime_error(error: str) -> tuple[str, str, str, bool]:
    """把沙箱报错归类为稳定错误码。

    Returns:
        (code, message, hint, repairable)
    """
    text = str(error or "").strip()
    if not text:
        text = "未知执行错误（无输出）"
    code = "CODE_RUNTIME_ERROR"
    for candidate, pattern in _ERROR_PATTERNS:
        if pattern.search(text):
            code = candidate
            break
    # 只保留最后一行/最有用的一行，避免把整段 stderr 塞进前端
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    message = lines[-1] if lines else text
    if len(message) > 500:
        message = message[:500] + "…"
    return code, message, _ERROR_HINTS.get(code, ""), code != "CODE_SECURITY_REJECTED"


def html_validation_issues(chart_path: str | Path) -> list[dict[str, Any]]:
    """校验 HTML 产物：存在、非空、包含 ECharts 容器。"""
    path = Path(chart_path) if chart_path else None
    if path is None:
        return [{
            "code": "CODE_HTML_MISSING",
            "message": "未返回 HTML 路径",
            "hint": _ERROR_HINTS["CODE_HTML_MISSING"],
            "repairable": True,
        }]
    if not path.exists():
        return [{
            "code": "CODE_HTML_MISSING",
            "message": f"HTML 不存在：{path}",
            "hint": _ERROR_HINTS["CODE_HTML_MISSING"],
            "repairable": True,
        }]
    try:
        size = path.stat().st_size
    except OSError as e:
        return [{
            "code": "CODE_HTML_MISSING",
            "message": f"无法读取 HTML：{e}",
            "hint": _ERROR_HINTS["CODE_HTML_MISSING"],
            "repairable": True,
        }]
    if size <= 0:
        return [{
            "code": "CODE_HTML_INVALID",
            "message": f"HTML 为空：{path}",
            "hint": _ERROR_HINTS["CODE_HTML_INVALID"],
            "repairable": True,
        }]

    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError as e:
        return [{
            "code": "CODE_HTML_INVALID",
            "message": f"HTML 读取失败：{e}",
            "hint": _ERROR_HINTS["CODE_HTML_INVALID"],
            "repairable": True,
        }]

    lower = text.lower()
    has_chart = (
        "echarts" in lower
        or "<canvas" in lower
        or "<svg" in lower
        or "chart-container" in lower
    )
    if not has_chart:
        return [{
            "code": "CODE_HTML_INVALID",
            "message": "HTML 中没有找到 ECharts/canvas/svg 图表容器",
            "hint": _ERROR_HINTS["CODE_HTML_INVALID"],
            "repairable": True,
        }]
    return []


def runtime_report(
    *,
    ok: bool,
    attempt: int,
    error: str = "",
    chart_path: str | Path = "",
    warnings: list | None = None,
) -> dict[str, Any]:
    """构建一次运行/产物校验报告。"""
    report = new_report(stage="runtime", attempt=attempt)
    if not ok:
        code, message, hint, repairable = classify_runtime_error(error)
        add_error(report, code, message, hint=hint, repairable=repairable)
    elif chart_path:
        for issue in html_validation_issues(chart_path):
            add_error(
                report,
                issue["code"],
                issue["message"],
                hint=issue.get("hint", ""),
                repairable=issue.get("repairable", True),
            )
    for warning in warnings or []:
        add_warning(report, "GENERATION_WARNING", warning)
    return report


def format_report_errors(report: dict) -> str:
    """把报告错误压成可回喂 debug 的文本。"""
    errors = report.get("errors") or []
    if not errors:
        return ""
    return "\n".join(
        f"[{e.get('code', 'ERROR')}] {e.get('message', '')}"
        + (f"\n建议：{e.get('hint')}" if e.get("hint") else "")
        for e in errors
    )


def build_generation_result(
    *,
    plan_id: str,
    ok: bool,
    attempts: int,
    duration_ms: float,
    code_path: str = "",
    html_path: str = "",
    report: dict | None = None,
    token_usage: dict | None = None,
) -> dict[str, Any]:
    """构建可序列化的 GenerationResult。"""
    report = report or new_report(attempt=attempts)
    report["ok"] = bool(ok and not report.get("errors"))
    return {
        "plan_id": str(plan_id),
        "ok": bool(ok and not report.get("errors")),
        "attempts": max(1, int(attempts)),
        "duration_ms": round(max(0.0, float(duration_ms)), 1),
        "code_path": str(code_path or ""),
        "html_path": str(html_path or ""),
        "token_usage": token_usage or {},
        "warnings": report.get("warnings", []),
        "validation": report,
    }


def write_generation_result(output_folder: str | Path, result: dict) -> Path:
    """把 GenerationResult 写到 plans/generation_<plan_id>.json。"""
    plans_folder = Path(output_folder) / "plans"
    plans_folder.mkdir(parents=True, exist_ok=True)
    plan_id = str(result.get("plan_id") or "unknown")
    # 只做最小文件系统清洗，避免 plan_id 中的路径分隔符逃出目录
    safe_id = re.sub(r"[^0-9A-Za-z_.-]+", "_", plan_id).strip("._") or "unknown"
    path = plans_folder / f"generation_{safe_id}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    logger.info("生成结果已保存", path=str(path), ok=result.get("ok"))
    return path
