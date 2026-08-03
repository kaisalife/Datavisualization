"""自动报告生成 DEMO（支持多国家对比）。

一句话生成宏观经济分析报告（类似腾讯开悟体验）。

运行方式：
    python demo_report_generation.py

用户只需要输入一句话，比如：
    "分析中国 GDP、人口和通胀趋势"
    "对比中美 GDP 和人口增长"
    "中美日三国失业率对比"
    "看一下中国近年的经济增长和就业情况"
"""
import asyncio
from pathlib import Path
import sys

# 确保能导入项目模块
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from service.report_pipeline import generate_report_from_prompt, get_default_llm


# 预置的示例请求
EXAMPLES = [
    "分析中国 GDP、人口和通胀趋势",
    "对比中美 GDP 和人口增长",
    "中美日三国失业率对比分析",
    "分析中国贸易依存度和城镇化水平",
]


async def main():
    print("=" * 70)
    print("📊 宏观经济自动报告生成 DEMO（支持多国家对比）")
    print("=" * 70)
    print()
    
    # Step 1: 加载 LLM
    print("🔧 加载 LLM 客户端...")
    llm = get_default_llm()
    if llm is None:
        print("⚠️  LLM 配置加载失败，将使用静态文案模式（无 AI 分析）")
    else:
        print(f"✅ LLM 加载成功：{llm.model}")
    print()
    
    # Step 2: 让用户选择或输入需求
    print("💡 请选择要分析的内容（输入编号或直接输入你的需求）：")
    for i, example in enumerate(EXAMPLES):
        print(f"   {i+1}. {example}")
    print()
    
    user_input = input("👉 你的选择：").strip()
    
    # 处理用户输入
    if user_input.isdigit() and 1 <= int(user_input) <= len(EXAMPLES):
        user_prompt = EXAMPLES[int(user_input) - 1]
    else:
        user_prompt = user_input
    
    if not user_prompt:
        user_prompt = EXAMPLES[0]
    
    print(f"\n📝 分析需求：{user_prompt}")
    print()
    
    # Step 3: 生成报告
    print("🚀 开始生成报告（约 10-40 秒，对比模式会久一点）...")
    print("   1/4 LLM 正在选择国家和指标...")
    print("   2/4 并发拉取数据...")
    print("   3/4 生成可视化图表...")
    print("   4/4 LLM 撰写分析报告...")
    print()
    
    result = await generate_report_from_prompt(
        user_prompt=user_prompt,
        llm_client=llm,
        start_year=2010,
    )
    
    if not result["success"]:
        print(f"❌ 生成失败：{result.get('error')}")
        if result.get("traceback"):
            print(result["traceback"])
        return 1
    
    # Step 4: 展示结果
    print("✅ 报告生成成功！")
    print()
    
    # 显示是否是对比模式
    is_compare = result.get("is_compare_mode", False)
    if is_compare:
        print("🔄 报告模式：多国家对比")
        print("   涉及国家：" + "、".join([c["name"] for c in result.get("countries", [])]))
    else:
        print("📊 报告模式：单国家分析")
        if result.get("countries"):
            print(f"   国家：{result['countries'][0]['name']}")
    print()
    
    print("📋 LLM 选择的指标：")
    for ind in result.get("selected_indicators", []):
        print(f"   - {ind['name']}：{ind.get('reason', '')}")
    print(f"   思路：{result.get('selection_explanation', '')}")
    print()
    
    report_path = result.get("report_path")
    if report_path:
        print(f"📄 报告文件：{report_path}")
        print()
        print("💡 提示：用浏览器打开上面的 HTML 文件即可查看完整报告")
        if is_compare:
            print("   📈 对比模式特色：每张图表包含多个国家的趋势线，可横向对比")
        print("   报告包含：目录、数据摘要、多图表 + 分析、结论建议、免责声明")
    
    print()
    print("=" * 70)
    
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
