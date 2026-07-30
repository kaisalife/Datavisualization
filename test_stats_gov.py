"""测试国家统计局 Adapter + 端到端报告生成。

运行:
    python test_stats_gov.py
"""
import asyncio
from pathlib import Path
import sys

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from service.viz_data.adapters.stats_gov_adapter import StatsGovAdapter
from service.report_pipeline import generate_report_from_prompt, get_default_llm


async def test_adapter_simple():
    """测试单个 Adapter 能否正常获取数据。"""
    print("=" * 60)
    print("测试 1: StatsGovAdapter 单指标获取（GDP）")
    print("=" * 60)

    adapter = StatsGovAdapter(indicator_code="GDP_QUARTERLY", start_year=2020)
    dataset = await adapter.fetch()

    print(f"数据集名称：{dataset.name}")
    print(f"数据行数：{dataset.tabular.row_count if dataset.tabular else 0}")
    print(f"列名：{[c.name for c in dataset.tabular.columns]}")
    print(f"前5行预览：")
    for row in dataset.tabular.preview_rows[1:6]:
        print(f"  {row}")

    assert dataset.tabular.row_count > 0, "应该获取到数据"
    print("✅ 通过")
    print()


async def test_end_to_end_report():
    """测试端到端生成中国宏观经济分析报告。"""
    print("=" * 60)
    print("测试 2: 端到端生成中国宏观经济分析报告")
    print("=" * 60)

    llm = get_default_llm()
    user_prompt = "分析2020年以来中国GDP、CPI和工业增加值的走势"

    print(f"用户需求：{user_prompt}")
    print("正在生成报告（约15-30秒）...")
    print()

    result = await generate_report_from_prompt(
        user_prompt=user_prompt,
        llm_client=llm,
        start_year=2020,
    )

    if not result["success"]:
        print(f"❌ 失败：{result.get('error')}")
        return 1

    print(f"✅ 报告生成成功！")
    print(f"  数据源：{result.get('data_source', '未知')}")
    print(f"  选择的指标：")
    for ind in result.get("selected_indicators", []):
        print(f"    - {ind.get('name')}: {ind.get('reason', '')}")
    print(f"  图表数量：{len(result.get('charts', []))}")
    print(f"  报告路径：{result.get('report_path')}")
    print()

    # 验证报告文件存在
    report_path = Path(result["report_path"])
    assert report_path.exists(), "报告文件应该存在"
    assert report_path.stat().st_size > 1000, "报告文件应该有内容"

    print("✅ 通过")
    print()
    return 0


async def main():
    try:
        await test_adapter_simple()
        await test_end_to_end_report()

        print("=" * 60)
        print("🎉 所有测试通过！")
        print("   国家统计局数据适配器 + 端到端报告生成工作正常")
        print("=" * 60)
        return 0
    except Exception as e:
        print(f"\n❌ 测试失败：{e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
