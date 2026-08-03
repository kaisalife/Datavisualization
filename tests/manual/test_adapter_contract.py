"""Adapter 契约测试。

对**所有已注册的 Adapter**执行统一的契约校验：
1. 必须满足 VizDataAdapterPort（Protocol 检查）
2. source_kind() 返回非空字符串
3. capabilities() 返回 AdapterCapabilities 值对象
4. descriptor() 返回合法的 SourceDescriptor
5. adapt() 能跑通并产出有效的 VizDataset
6. VizDataset.descriptor 已被填充

新增数据源时，只要注册进 DataSourceRegistry 且请求参数能匹配，
这组测试会自动覆盖。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# 触发注册装饰器
from service.viz_data import adapters  # noqa: F401
from service.viz_data.capabilities import AdapterCapabilities
from service.viz_data.ports import VizDataAdapterPort
from service.viz_data.registry import DataSourceRegistry
from service.viz_data.schema import VizDataset
from service.viz_data.source_descriptor import SourceDescriptor


# ============================================================
# 每个 Adapter 的最小可用请求 fixture
# ============================================================

def _sample_db_path() -> str:
    db = _ROOT / "test_env" / "databases" / "sample.db"
    if not db.exists():
        build = _ROOT / "test_env" / "databases" / "build_sample_db.py"
        if build.exists():
            import subprocess
            subprocess.run([sys.executable, str(build)], check=True, cwd=str(_ROOT))
    if not db.exists():
        raise RuntimeError(f"sample.db missing at {db}")
    return str(db.resolve())


def _sample_csv_path() -> str:
    """构造一个临时 CSV 文件用于 FileAdapter 契约测试。"""
    import pandas as pd
    tmp = _ROOT / "test_env" / "_tmp_contract"
    tmp.mkdir(parents=True, exist_ok=True)
    csv_path = tmp / "sample_contract.csv"
    if not csv_path.exists():
        df = pd.DataFrame({"month": ["Jan", "Feb", "Mar"],
                           "sales": [100, 200, 150]})
        df.to_csv(csv_path, index=False, encoding="utf-8")
    return str(csv_path.resolve())


def _make_request_for(name: str):
    """根据 spec 名字构造能匹配该 Adapter 的最小请求对象。"""
    if name == "database":
        return SimpleNamespace(
            db_config={
                "db_type": "sqlite",
                "database": _sample_db_path(),
                "query": "SELECT * FROM sales LIMIT 3",   # 走 explicit query 路径，避开 LLM
            },
            user_prompt="",
            file_paths=None,
        )
    if name == "file":
        return SimpleNamespace(
            file_paths=[_sample_csv_path()],
            user_prompt="",
            db_config=None,
        )
    raise NotImplementedError(f"未定义 spec={name} 的 fixture，请在此补充")


# ============================================================
# 契约断言
# ============================================================

async def _assert_contract(name: str) -> None:
    print(f"\n---- 校验 Adapter: {name} ----")
    request = _make_request_for(name)
    adapter = DataSourceRegistry.resolve(request)

    # 1. Protocol 检查
    assert isinstance(adapter, VizDataAdapterPort), \
        f"{type(adapter).__name__} 不满足 VizDataAdapterPort"
    print("  ✅ Protocol 检查通过")

    # 2. source_kind
    kind = adapter.source_kind()
    assert isinstance(kind, str) and kind, f"source_kind() 非法: {kind!r}"
    print(f"  ✅ source_kind={kind}")

    # 3. capabilities
    caps = adapter.capabilities()
    assert isinstance(caps, AdapterCapabilities), \
        f"capabilities() 应返回 AdapterCapabilities，实际: {type(caps).__name__}"
    print(f"  ✅ capabilities: needs_llm={caps.needs_llm}, "
          f"multi_query={caps.supports_multi_query}")

    # 4. descriptor
    desc = adapter.descriptor()
    assert isinstance(desc, SourceDescriptor)
    assert desc.logical_id and "/" not in desc.logical_id and "\\" not in desc.logical_id, \
        f"logical_id 不能含路径分隔符: {desc.logical_id!r}"
    assert desc.label, "descriptor.label 不能为空"
    print(f"  ✅ descriptor: kind={desc.kind}, label={desc.label!r}, "
          f"logical_id={desc.logical_id!r}")

    # 5. adapt() 端到端
    dataset = await adapter.adapt(engine=None)
    assert isinstance(dataset, VizDataset), "adapt() 应返回 VizDataset"
    assert dataset.dataset_id, "dataset_id 不能为空"
    assert dataset.source_kind == kind, \
        f"dataset.source_kind({dataset.source_kind}) 与 adapter.source_kind({kind}) 不一致"

    # 6. descriptor 已被填充
    assert dataset.descriptor is not None, "dataset.descriptor 应被 adapt() 自动填充"
    assert isinstance(dataset.descriptor, SourceDescriptor)

    # 7. logical_id 可派生
    assert dataset.logical_id(), "logical_id() 派生失败"
    print(f"  ✅ VizDataset: id={dataset.dataset_id}, "
          f"logical_id={dataset.logical_id()}, "
          f"rows={dataset.tabular.row_count if dataset.tabular else 0}")

    # 清理临时目录
    dataset.cleanup()


async def main():
    sources = DataSourceRegistry.list_sources()
    print(f"已注册 Adapter: {sources}")
    for name in sources:
        try:
            await _assert_contract(name)
        except NotImplementedError as e:
            print(f"  ⚠️ 跳过 {name}: {e}")
    print("\n🎉 契约测试全部通过")


if __name__ == "__main__":
    asyncio.run(main())
