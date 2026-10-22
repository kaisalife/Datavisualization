"""图表资产登记：一次任务产出的可视化管理清单。

每个输出目录（``runtime/charts/<数据集名>/``）维护一份 ``assets.json``，
记录该目录产出过哪些图表文件（谁、何时、用什么 plan/series/代码）。
ORM 时代的对应物不存在——图表本体是 HTML + 自包含代码，登记表只是索引。

用途（对应多轮对话二次优化需求）：

- 前端"当前对话生成资产"列表（chart_id / 标题 / 类型 / plan 摘要）；
- 二次优化入口：拿 chart_id 反查原始 plan、series 数据路径、成功代码；
- 优化产物同样登记（``origin_chart_id`` 指向原图，``version`` 递增），
  历史 HTML/代码永不覆盖（旧行可回看）。

登记失败绝不影响图表本身（只记日志，弱依赖）。
"""
from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from service.observability import get_logger

logger = get_logger(__name__)

# 同一任务的图表是并发生成的（chart_executor 信号量），每个成功图都会登记 assets。
# 读-改-写必须串行，否则两张图同时完成时后写者会覆盖前者的记录，
# 前端就找不到可二次优化的图。写操作很少，全局锁足够。
_ASSETS_LOCK = threading.RLock()

ASSETS_FILENAME = "assets.json"


def _assets_file(output_folder: str | Path) -> Path:
    return Path(output_folder) / ASSETS_FILENAME


def load_assets(output_folder: str | Path) -> list[dict[str, Any]]:
    """读取一个输出目录的资产清单（缺失/损坏返回空列表）。"""
    path = _assets_file(output_folder)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [item for item in data if isinstance(item, dict)]
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("图表资产清单解析失败", file=str(path), error=str(e))
        return []


def record_chart(
    output_folder: str | Path,
    *,
    task_id: str = "",
    conversation_id: str = "",
    plan: dict | None = None,
    chart_path: str,
    code_path: str = "",
    data_path: str = "",
    origin_chart_id: str = "",
    version: int = 0,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """向输出目录追加一条图表资产记录（弱依赖：失败只记日志）。

    Args:
        output_folder: 输出目录（runtime/charts/<数据集名>/）。
        task_id / conversation_id: 来源任务/对话（可用于前端资产过滤）。
        plan: plan dict（取 plan_id/plan_name/chart_type_series_id 摘要）。
        chart_path: HTML 文件绝对路径。
        code_path: 自包含代码文件路径（可为空）。
        data_path: series .parquet 绝对路径（自备读取模式为空）。
        origin_chart_id: 二次优化场景指向被优化的原图 chart_id。
        version: 优化版本号（原图 0，第一次优化 1…）。
        extra: 附加字段（如优化指令摘要）。

    Returns:
        dict: 登记成功的记录；登记失败返回 None（不抛错）。
    """
    try:
        from Entity.plan_models import plan_get
    except ImportError:
        from ..plan_models import plan_get  # type: ignore  # pragma: no cover

    chart_file = Path(chart_path)
    record = {
        "chart_id": chart_file.name,
        "chart_path": str(chart_file),
        "code_path": str(code_path or ""),
        "data_path": str(data_path or ""),
        "output_folder": str(output_folder),
        "task_id": str(task_id or ""),
        "conversation_id": str(conversation_id or ""),
        "plan_id": str(plan_get(plan, "plan_id", "") if plan else ""),
        "plan_name": str(plan_get(plan, "plan_name", "") if plan else ""),
        "chart_title": str(plan_get(plan, "chart_title", "") if plan else ""),
        "chart_type": str(plan_get(plan, "chart_type", "") if plan else ""),
        "series_id": str(plan_get(plan, "series_id", "") if plan else ""),
        "origin_chart_id": str(origin_chart_id or ""),
        "version": int(version),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    if extra:
        record.update(extra)
    try:
        with _ASSETS_LOCK:
            assets = load_assets(output_folder)
            assets.append(record)
            path = _assets_file(output_folder)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(assets, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(path)
        return record
    except Exception as e:
        logger.warning(
            "图表资产登记失败", chart_id=record["chart_id"], error=str(e)
        )
        return None


def find_asset_by_chart_id(chart_id: str, charts_root: str | Path | None = None) -> dict[str, Any] | None:
    """按 chart_id 反查资产记录（在 charts 根目录下递归找 assets.json）。

    Args:
        chart_id: HTML 文件名（如 ``chart_p1_20261022_153000.html``），
            不允许包含路径分隔符（调用方先做穿越校验）。
        charts_root: 图表根目录；缺省用 ``get_charts_dir()``。

    Returns:
        dict: 命中的资产记录；找不到返回 None。
    """
    chart_id = str(chart_id or "").strip()
    if not chart_id or "/" in chart_id or "\\" in chart_id or ".." in chart_id:
        return None
    if charts_root is None:
        from service.runtime.constants import get_charts_dir

        charts_root = get_charts_dir()
    root = Path(charts_root)
    if not root.is_dir():
        return None
    for assets_file in sorted(root.rglob(ASSETS_FILENAME)):
        for item in load_assets(assets_file.parent):
            if item.get("chart_id") == chart_id:
                # 校验产物仍存在（被手工清理的资产不返回）
                if Path(item.get("chart_path", "")).is_file():
                    return item
                return None
    return None


def next_optimize_version(assets: list[dict[str, Any]], origin_chart_id: str) -> int:
    """某张图已有优化版本数 + 1（用于新版本命名与登记）。"""
    return 1 + sum(
        1 for item in assets
        if str(item.get("origin_chart_id") or "") == str(origin_chart_id)
    )


def asset_card(item: dict[str, Any]) -> dict[str, Any]:
    """资产记录 -> 前端卡片字段（只暴露展示/交互所需，不含路径细节）。"""
    title = str(item.get("chart_title") or item.get("plan_name") or "")
    return {
        "chart_id": str(item.get("chart_id") or ""),
        "title": title,
        "chart_type": str(item.get("chart_type") or ""),
        "plan_id": str(item.get("plan_id") or ""),
        "version": int(item.get("version") or 0),
        "origin_chart_id": str(item.get("origin_chart_id") or ""),
        "optimize_prompt": str(item.get("optimize_prompt") or ""),
        "created_at": str(item.get("created_at") or ""),
    }


def find_task_assets(task_id: str, charts_root: str | Path | None = None) -> list[dict[str, Any]]:
    """按 task_id 过滤全部资产记录并输出卡片（rglob assets.json，量级为目录数）。"""
    task_id = str(task_id or "")
    if not task_id:
        return []
    if charts_root is None:
        from service.runtime.constants import get_charts_dir

        charts_root = get_charts_dir()
    root = Path(charts_root)
    if not root.is_dir():
        return []
    cards: list[dict[str, Any]] = []
    for assets_file in sorted(root.rglob(ASSETS_FILENAME)):
        for item in load_assets(assets_file.parent):
            if str(item.get("task_id") or "") == task_id:
                card = asset_card(item)
                if card["chart_id"] and Path(item.get("chart_path", "")).is_file():
                    cards.append(card)
    return cards
