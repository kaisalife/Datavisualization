"""DatabaseAdapter + QueryPlanner 依赖注入的单元测试。

验证：
1. 用 FakePlanner 注入后，DatabaseAdapter.fetch 不再依赖 QueryEngine/LLM
2. Query 值对象在 fetch 流程里正确流转
3. single/auto/per_table 三种模式均正常
4. explicit query（db_config.query）短路，不调用 planner
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# 加入项目根到 sys.path
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from service.viz_data.adapters.database_adapter import DatabaseAdapter
from service.viz_data.planning.query_planner import Query


class FakePlanner:
    """假 QueryPlanner，记录调用参数，返回预设 Query 列表。"""

    def __init__(self, response: list[Query]):
        self.response = response
        self.called_with: list[dict] = []

    async def plan(self, *, schema_text, user_prompt, hint=None, max_queries=1):
        self.called_with.append({
            "schema_text": schema_text,
            "user_prompt": user_prompt,
            "hint": hint,
            "max_queries": max_queries,
        })
        return list(self.response[:max_queries])


def _prepare_sample_db() -> str:
    """确保 sample.db 存在（复用 test_env 下的样本）。"""
    sample = _ROOT / "test_env" / "databases" / "sample.db"
    if not sample.exists():
        # 若不存在则尝试构建
        build_script = _ROOT / "test_env" / "databases" / "build_sample_db.py"
        if build_script.exists():
            import subprocess
            subprocess.run(
                [sys.executable, str(build_script)],
                check=True,
                cwd=str(_ROOT),
            )
    if not sample.exists():
        raise RuntimeError(f"sample db not found: {sample}")
    return str(sample.resolve())


async def test_explicit_query_no_planner_call():
    """db_config.query 存在时，planner 不应被调用。"""
    db_path = _prepare_sample_db()
    fake = FakePlanner(response=[])
    adapter = DatabaseAdapter(
        db_config={
            "db_type": "sqlite",
            "database": db_path,
            "query": "SELECT * FROM sales LIMIT 5",
        },
        user_prompt="",
        planner=fake,
    )
    dataset = await adapter.adapt(engine=None)
    assert dataset is not None
    assert dataset.tabular is not None
    assert dataset.tabular.row_count <= 5
    assert len(fake.called_with) == 0, "explicit query 场景不应调用 planner"
    dataset.cleanup()
    print("✅ test_explicit_query_no_planner_call passed")


async def test_single_mode_uses_injected_planner():
    """single 模式下，注入的 planner 应被调用一次，max_queries=1。"""
    db_path = _prepare_sample_db()
    fake = FakePlanner(response=[
        Query(body="SELECT * FROM sales LIMIT 3", name="query_result",
              explanation="fake", dialect="sql"),
    ])
    adapter = DatabaseAdapter(
        db_config={
            "db_type": "sqlite",
            "database": db_path,
        },
        user_prompt="show me sales data",
        planner=fake,
    )
    dataset = await adapter.adapt(engine=None)
    assert dataset is not None
    assert dataset.tabular is not None
    assert dataset.tabular.row_count == 3
    assert len(fake.called_with) == 1
    assert fake.called_with[0]["max_queries"] == 1
    assert fake.called_with[0]["user_prompt"] == "show me sales data"
    dataset.cleanup()
    print("✅ test_single_mode_uses_injected_planner passed")


async def test_auto_mode_multi_queries():
    """auto 模式下，注入的 planner 可返回多条查询，产出 related_datasets。"""
    db_path = _prepare_sample_db()
    fake = FakePlanner(response=[
        Query(body="SELECT * FROM sales LIMIT 3", name="q1"),
        Query(body="SELECT * FROM sales LIMIT 5", name="q2"),
    ])
    adapter = DatabaseAdapter(
        db_config={
            "db_type": "sqlite",
            "database": db_path,
            "multi_query_mode": "auto",
            "max_queries": 3,
        },
        user_prompt="analyze",
        planner=fake,
    )
    dataset = await adapter.adapt(engine=None)
    assert dataset is not None
    assert dataset.tabular is not None
    assert len(dataset.related_datasets) == 1, \
        f"应有 1 个 related dataset，实际: {len(dataset.related_datasets)}"
    assert len(fake.called_with) == 1
    assert fake.called_with[0]["max_queries"] == 3
    dataset.cleanup()
    print("✅ test_auto_mode_multi_queries passed")


async def test_per_table_no_planner_call():
    """per_table 模式下，planner 不应被调用。"""
    db_path = _prepare_sample_db()
    fake = FakePlanner(response=[])
    adapter = DatabaseAdapter(
        db_config={
            "db_type": "sqlite",
            "database": db_path,
            "multi_query_mode": "per_table",
            "max_queries": 1,
        },
        user_prompt="",
        planner=fake,
    )
    dataset = await adapter.adapt(engine=None)
    assert dataset is not None
    assert len(fake.called_with) == 0, "per_table 模式不应调用 planner"
    dataset.cleanup()
    print("✅ test_per_table_no_planner_call passed")


async def main():
    await test_explicit_query_no_planner_call()
    await test_single_mode_uses_injected_planner()
    await test_auto_mode_multi_queries()
    await test_per_table_no_planner_call()
    print("\n🎉 全部单元测试通过")


if __name__ == "__main__":
    asyncio.run(main())
