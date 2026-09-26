"""阶段 2 计划 agent 会话状态。

跨工具共享的共享内存：
- catalog / profile: 计划依据（语义 series 目录 + 数据画像）
- plans / dropped: agent 提交的 plan 汇总（校验通过或降级的进 plans，丢弃的进 dropped）
- tried: series 加载缓存（多 plan 同 series 只全量读一次）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from service.data_ingestion.series.models import SeriesCatalog


@dataclass
class PlanSessionState:
    """一次阶段 2 agent 会话的共享状态。"""

    catalog: SeriesCatalog
    agent_logs: list
    profile: Any = None
    plans: list[dict] = field(default_factory=list)
    dropped: list[dict] = field(default_factory=list)
    tried: dict = field(default_factory=dict)
    name: str = "plan_session"

    def plan_count(self) -> int:
        return len(self.plans) + len(self.dropped)

    def summary(self) -> str:
        """供 agent 查看的提交进度摘要。"""
        parts = [f"已提交 plan 数: {self.plan_count()}"]
        for i, p in enumerate(self.plans, 1):
            status = "降级" if p.get("degraded") else "通过"
            parts.append(
                f"  {i}. [{status}] {p.get('plan_id', '?')} {p.get('plan_name', '')} "
                f"series={p.get('series_id', '-')}"
            )
        for p in self.dropped:
            parts.append(f"  [丢弃] {p.get('plan_id', '?')} {p.get('plan_name', '')}")
        return "\n".join(parts)