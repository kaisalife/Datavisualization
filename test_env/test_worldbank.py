"""测试 WorldBankAdapter 和报告生成器。

运行方式：
    cd test_env
    python -m test_worldbank
"""
import asyncio
from pathlib import Path
import sys

# 添加项目根目录
sys.path.insert(0, str(Path(__file__).parent.parent))

from service.viz_data.adapters.worldbank_adapter import WorldBankAdapter
from service.report_generator import generate_and_save_report


async def test_worldbank_adapter():
    """测试获取 GDP 数据。"""
    print("=" * 60)
    print("测试 WorldBankAdapter")
    print("=" * 60)
    
    # 获取中国 GDP 数据（2010-2024）
    adapter = WorldBankAdapter(
        indicator="NY.GDP.MKTP.CD",  # GDP（现价美元）
        country="CN",
        start_year=2010,
        end_year=2024,
    )
    
    dataset = await adapter.fetch()
    
    print(f"\n✓ 数据集名称：{dataset.name}")
    print(f"✓ 行数：{dataset.tabular.row_count if dataset.tabular else 0}")
    
    if dataset.tabular and dataset.tabular.preview_rows:
        cols = dataset.tabular.preview_rows[0]
        print(f"✓ 列名：{cols}")
        print(f"\n前 5 行数据：")
        for row in dataset.tabular.preview_rows[1:6]:
            print(f"  {row}")
    
    # 测试关键词解析
    print(f"\n✓ 关键词 'GDP' 解析为：{WorldBankAdapter.resolve_indicator('GDP')}")
    print(f"✓ 关键词 '人口' 解析为：{WorldBankAdapter.resolve_indicator('POPULATION')}")
    
    return dataset


async def test_multi_indicators():
    """测试获取多个指标并生成对比报告。"""
    print("\n" + "=" * 60)
    print("测试多指标对比")
    print("=" * 60)
    
    indicators = [
        ("NY.GDP.MKTP.CD", "GDP"),
        ("NY.GDP.PCAP.CD", "人均GDP"),
        ("SP.POP.TOTL", "总人口"),
    ]
    
    datasets = []
    for code, name in indicators:
        adapter = WorldBankAdapter(indicator=code, country="CN", start_year=2010, end_year=2024)
        dataset = await adapter.fetch()
        datasets.append(dataset)
        print(f"✓ 获取 {name} 数据：{dataset.tabular.row_count if dataset.tabular else 0} 行")
    
    return datasets


async def test_report_generation(datasets):
    """测试报告生成（无 LLM 版本）。"""
    print("\n" + "=" * 60)
    print("测试报告生成")
    print("=" * 60)
    
    # 伪造几个图表（简单 HTML，实际应该走可视化管线）
    charts = [
        '<div style="height: 400px; background: #f5f5f5; display: flex; align-items: center; justify-content: center;">图表 1（折线图：GDP 趋势）</div>',
        '<div style="height: 400px; background: #f5f5f5; display: flex; align-items: center; justify-content: center;">图表 2（柱状图：人均GDP）</div>',
    ]
    
    output_path = Path(__file__).parent / "output" / "gdp_report.html"
    
    # 生成报告（无 LLM，用降级文案）
    saved_path = await generate_and_save_report(
        output_path=str(output_path),
        title="中国宏观经济数据分析报告",
        datasets=datasets,
        charts=charts,
        user_prompt="分析中国 GDP 和人口趋势",
        llm_client=None,  # 不传入 LLM，用降级文案
    )
    
    print(f"✓ 报告已生成：{saved_path}")
    print(f"  文件大小：{saved_path.stat().st_size / 1024:.1f} KB")
    
    return saved_path


async def main():
    try:
        # 1. 测试单指标
        dataset = await test_worldbank_adapter()
        
        # 2. 测试多指标
        datasets = await test_multi_indicators()
        
        # 3. 测试报告生成
        report_path = await test_report_generation(datasets)
        
        print("\n" + "=" * 60)
        print("✅ 所有测试通过！")
        print(f"📄 报告文件：{report_path}")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ 测试失败：{e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
