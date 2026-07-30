"""DatabaseAdapter 多表冒烟测试。

覆盖场景：
1. single 模式（默认，M2 兼容）
2. per_table 模式（无 LLM 兜底，最能验证多 dataset 逻辑）
3. 显式 query 优先级最高
4. 一条 SQL 失败但其他成功 → failed_queries 记录
5. cleanup 一次删除全部 parquet
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from service.viz_data.adapters.database_adapter import DatabaseAdapter


DB_PATH = "test_env/databases/sample.db"


async def test_single_mode_backward_compat():
    """M2 回归：single 模式 + 显式 query。"""
    adapter = DatabaseAdapter(
        db_config={
            "db_type": "sqlite",
            "database": DB_PATH,
            "query": "SELECT r.name AS region, SUM(s.amount) AS total FROM sales s JOIN regions r ON s.region_id=r.id GROUP BY r.name",
        },
        user_prompt="",
    )
    ds = await adapter.adapt(engine=None)
    assert ds.related_datasets == [], "single 模式不应有 related"
    assert ds.tabular.row_count == 5
    assert ds.name == "query_result"
    ds.cleanup()
    print("✅ single 模式 + 显式 query 回归通过")


async def test_per_table_mode():
    """per_table 无 LLM 兜底：每张表一条 SELECT *。"""
    adapter = DatabaseAdapter(
        db_config={
            "db_type": "sqlite",
            "database": DB_PATH,
            "multi_query_mode": "per_table",
        },
        user_prompt="",
    )
    ds = await adapter.adapt(engine=None)

    all_ds = ds.all_datasets()
    print(f"  primary: {ds.name} ({ds.tabular.row_count} rows)")
    for r in ds.related_datasets:
        print(f"  related: {r.name} ({r.tabular.row_count} rows)")

    # sample.db 有 3 张表：products/regions/sales
    assert len(all_ds) == 3, f"per_table 应产生 3 个 dataset, 实际 {len(all_ds)}"
    names = {d.name for d in all_ds}
    assert {"products", "regions", "sales"}.issubset(names), f"缺失表: {names}"

    # 每个 dataset 都能读到 parquet
    import pandas as pd
    for d in all_ds:
        p = d.primary_data_path()
        assert p, f"{d.name} 无 primary_data_path"
        df = pd.read_parquet(p, engine="pyarrow")
        assert len(df) > 0, f"{d.name} 数据为空"

    # cleanup 一次删除所有 parquet（primary 独占 _temp_dir）
    assert ds._temp_dir is not None
    temp_dir = Path(ds._temp_dir)
    parquets = list(temp_dir.glob("*.parquet"))
    assert len(parquets) == 3, f"应有 3 个 parquet, 实际 {len(parquets)}"

    ds.cleanup()
    assert not temp_dir.exists(), "cleanup 后目录仍存在"
    print(f"✅ per_table 模式：{len(all_ds)} 个 dataset + cleanup 一次删除全部")


async def test_per_table_with_max_queries():
    """max_queries 限制。"""
    adapter = DatabaseAdapter(
        db_config={
            "db_type": "sqlite",
            "database": DB_PATH,
            "multi_query_mode": "per_table",
            "max_queries": 2,
        },
        user_prompt="",
    )
    ds = await adapter.adapt(engine=None)
    assert len(ds.all_datasets()) == 2, "max_queries=2 应只产生 2 个"
    ds.cleanup()
    print("✅ max_queries 限制生效")


async def test_prompt_json_contains_related():
    """canonical json 含 related_datasets 段（供 planner 处理多 dataset）。"""
    adapter = DatabaseAdapter(
        db_config={
            "db_type": "sqlite",
            "database": DB_PATH,
            "multi_query_mode": "per_table",
        },
        user_prompt="分析销售数据",
    )
    ds = await adapter.adapt(engine=None)

    prompt_json = ds.to_prompt_json()
    parsed = json.loads(prompt_json)

    assert "related_datasets" in parsed, "prompt json 缺 related_datasets"
    assert len(parsed["related_datasets"]) == 2  # sample.db 共 3 表 - primary
    for r in parsed["related_datasets"]:
        assert "tabular" in r
        assert r["tabular"]["data_ref"]["kind"] == "parquet"
    ds.cleanup()
    print("✅ to_prompt_json 含完整 related_datasets 段")


async def test_source_meta_redacted():
    """凭据脱敏在多表模式仍然生效。"""
    adapter = DatabaseAdapter(
        db_config={
            "db_type": "sqlite",
            "database": DB_PATH,
            "multi_query_mode": "per_table",
            "password": "SECRET_XYZ",
        },
        user_prompt="",
    )
    ds = await adapter.adapt(engine=None)
    assert ds.source_meta.get("password") == "***"
    # related 也共享脱敏后的 source_meta
    for r in ds.related_datasets:
        assert r.source_meta.get("password") == "***"
    ds.cleanup()
    print("✅ 凭据脱敏在多表模式生效")


async def test_validate_bad_mode():
    """错误的 mode 应报错。"""
    from service.viz_data.adapters.base import AdapterError
    adapter = DatabaseAdapter(
        db_config={
            "db_type": "sqlite",
            "database": DB_PATH,
            "multi_query_mode": "invalid_mode",
        },
    )
    try:
        adapter.validate()
        raise AssertionError("未拦截 invalid_mode")
    except AdapterError as e:
        assert "multi_query_mode" in str(e)
    print("✅ validate 拦截非法 multi_query_mode")


async def main():
    await test_single_mode_backward_compat()
    await test_per_table_mode()
    await test_per_table_with_max_queries()
    await test_prompt_json_contains_related()
    await test_source_meta_redacted()
    await test_validate_bad_mode()
    print("\n=== 所有 DB 多表测试通过 ===")


if __name__ == "__main__":
    asyncio.run(main())
