"""QueryPlanner 领域服务：把 (schema + user_prompt) 规划成查询列表。

抽象出来后：
- DatabaseAdapter 不再直接依赖 LLM prompts
- 未来非 SQL 源（Mongo / GraphQL）也可以复用同一端口
- 可用 FakePlanner 做单元测试
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Query:
    """一条可执行的数据查询（值对象）。

    Fields:
        body: 查询语句本体（SQL 字符串 / Mongo pipeline JSON / GraphQL query）
        name: 结果集命名，用于 parquet 落盘文件名和 dataset name
        explanation: LLM/规划器对该查询的解释，供审计和 UI 展示
        dialect: 查询方言，用于驱动层选择执行器
    """

    body: str
    name: str
    explanation: str = ""
    dialect: str = "sql"

    # 兼容旧代码里使用 dict 的位置：提供便捷转换
    def to_legacy_dict(self) -> dict:
        """转成旧代码里流转的 dict 形式（sql/name/explanation）。"""
        return {
            "sql": self.body,
            "name": self.name,
            "explanation": self.explanation,
        }
