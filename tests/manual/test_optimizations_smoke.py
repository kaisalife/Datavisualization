"""OPT-1/2/3 冒烟测试：静态验证优化项落地。"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_opt1_prompt_has_canonical_dataset():
    """OPT-1: chart_designer_prompt human 模板含 canonical_dataset 变量。"""
    from prompts.agent_prompt import get_agent_chart_designer_prompt

    tpl = get_agent_chart_designer_prompt()
    human_msg = tpl.messages[-1]
    tpl_str = human_msg.prompt.template if hasattr(human_msg, "prompt") else str(human_msg)
    assert "{canonical_dataset}" in tpl_str, f"human 缺 canonical_dataset 变量: {tpl_str}"

    # 系统提示中含关键指导语
    system_msg = tpl.messages[0]
    system_str = system_msg.prompt.template if hasattr(system_msg, "prompt") else str(system_msg)
    assert "canonical_dataset" in system_str, "system prompt 未提及 canonical_dataset"
    assert "semantic_role" in system_str, "system prompt 未提及 semantic_role"
    assert "related_datasets" in system_str, "system prompt 未提及 related_datasets（多数据集处理）"

    # 兜底：partial_variables 有 canonical_dataset
    assert tpl.partial_variables.get("canonical_dataset") == "(未提供)"

    print("✅ OPT-1: canonical_dataset 变量已注入 planner prompt")


def test_opt2_generate_prompt_has_dataset_summary():
    """OPT-2: generate/debug prompt human 模板含 dataset_summary 占位符。"""
    from prompts.agent_prompt import (
        get_agent_generate_chart_prompt,
        get_agent_debug_chart_prompt,
    )

    gen = get_agent_generate_chart_prompt()
    # 直接检查 human 模板字符串（不做完整 invoke，因为 system 有其他变量）
    human_msg = gen.messages[-1]
    tpl_str = human_msg.prompt.template if hasattr(human_msg, "prompt") else str(human_msg)
    assert "{dataset_summary}" in tpl_str, f"generate human 缺 dataset_summary 变量: {tpl_str}"
    # 验证 partial 兜底
    assert "dataset_summary" in gen.input_variables or gen.partial_variables.get("dataset_summary") == "(未提供)"

    dbg = get_agent_debug_chart_prompt()
    human_msg = dbg.messages[-1]
    tpl_str = human_msg.prompt.template if hasattr(human_msg, "prompt") else str(human_msg)
    assert "{dataset_summary}" in tpl_str, f"debug human 缺 dataset_summary 变量: {tpl_str}"

    print("✅ OPT-2: dataset_summary 变量在 generate/debug human 模板中")


def test_opt2_chart_generator_signature():
    """OPT-2: generate_single_chart 支持 dataset_summary 参数。"""
    import inspect
    from service.chart_generator import generate_single_chart

    sig = inspect.signature(generate_single_chart)
    assert "dataset_summary" in sig.parameters, "缺 dataset_summary 参数"
    assert sig.parameters["dataset_summary"].default == "", "dataset_summary 默认值应为空字符串"
    print("✅ OPT-2: generate_single_chart 签名兼容")


async def test_opt3_multi_file_dataset():
    """OPT-3: FileAdapter 多文件 → related_datasets。"""
    from service.viz_data.adapters.file_adapter import FileAdapter

    # 用同一个 csv 传两次模拟多文件
    csv_path = "test_env/data_files/季度数据.csv"
    adapter = FileAdapter([csv_path, csv_path])
    ds = await adapter.adapt(engine=None)

    print(f"primary dataset_id = {ds.dataset_id}")
    print(f"related count = {len(ds.related_datasets)}")
    print(f"all datasets = {[d.dataset_id for d in ds.all_datasets()]}")

    assert len(ds.related_datasets) == 1, "应有 1 个 related"
    assert len(ds.all_datasets()) == 2, "all_datasets 应=2"
    assert ds._temp_dir is not None, "primary 应有 _temp_dir"
    assert ds.related_datasets[0]._temp_dir is None, "related 不应重复挂 _temp_dir"

    # to_prompt_json 含 related_datasets 段
    prompt_json = ds.to_prompt_json()
    parsed = json.loads(prompt_json)
    assert "related_datasets" in parsed, "prompt json 缺 related_datasets"
    assert len(parsed["related_datasets"]) == 1

    # 记录目录，用于验证 cleanup 后消失
    temp_dir = Path(ds._temp_dir)
    assert temp_dir.exists()
    parquet_files_before = list(temp_dir.glob("*.parquet"))
    print(f"cleanup 前 parquet 文件数: {len(parquet_files_before)}")

    ds.cleanup()
    assert not temp_dir.exists(), "cleanup 后目录仍存在"
    print("✅ OPT-3: FileAdapter 多文件 → related_datasets + 共享 cleanup")


async def test_opt3_single_file_backward_compat():
    """OPT-3: 单文件行为不变（回归）。"""
    from service.viz_data.adapters.file_adapter import FileAdapter

    adapter = FileAdapter(["test_env/data_files/季度数据.csv"])
    ds = await adapter.adapt(engine=None)

    assert ds.related_datasets == [], "单文件时 related 应为空"
    assert len(ds.all_datasets()) == 1
    assert ds.primary_data_path() is not None
    prompt_json = ds.to_prompt_json()
    parsed = json.loads(prompt_json)
    assert "related_datasets" not in parsed, "单文件时不应输出 related_datasets 键"

    ds.cleanup()
    print("✅ OPT-3: 单文件回归兼容")


async def main():
    test_opt1_prompt_has_canonical_dataset()
    test_opt2_generate_prompt_has_dataset_summary()
    test_opt2_chart_generator_signature()
    await test_opt3_multi_file_dataset()
    await test_opt3_single_file_backward_compat()
    print("\n=== 所有 OPT 测试通过 ===")


if __name__ == "__main__":
    asyncio.run(main())
