import asyncio
import os
import sys
from pathlib import Path

# 设置项目根目录
project_root = Path(__file__).parent.parent

# 添加到Python路径并切换工作目录
sys.path.insert(0, str(project_root))
os.chdir(project_root)

from dotenv import load_dotenv

# 导入模块 - 直接从具体文件导入，简化流程
try:
    from Entity.ApiModels import GenerateChartWithPromptRequest
    from service.service_main import service_main
    from service.config import load_config
    
    print("✅ 导入成功")
except Exception as e:
    print(f"❌ 导入失败: {e}")
    print(f"当前Python路径: {sys.path[:5]}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 加载.env文件
env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)

async def test_service_main():
    """测试service_main函数"""
    print("=" * 60)
    print("开始测试service_main函数")
    print("=" * 60)
    
    # 从环境变量获取配置
    model_name = os.getenv("MODEL_NAME") or os.getenv("MODEL_NAME_KIMI2.5", "kimi2.5")
    model_url = os.getenv("BASE_URL") or os.getenv("BASE_URL_WWCQ", "https://open.bigmodel.cn/api/paas/v4/")
    model_api_key = os.getenv("API_KEY") or os.getenv("API_KEY_WWCQ", "")
    
    print(f"\n使用模型: {model_name}")
    print(f"模型URL: {model_url}")
    print(f"API密钥: {'已设置' if model_api_key else '未设置'}")
    
    # 数据文件路径：命令行参数优先，其次环境变量，最后项目内默认路径
    DEFAULT_DATA_FILE = str(project_root / "test_env" / "data_files" / "季度数据.csv")
    data_file = sys.argv[1] if len(sys.argv) > 1 else os.getenv("TEST_DATA_FILE", DEFAULT_DATA_FILE)
    if not Path(data_file).exists():
        print(f"❌ 数据文件不存在: {data_file}")
        print(f"用法: python test_plan.py <数据文件路径>")
        print(f"  或设置环境变量 TEST_DATA_FILE=<数据文件路径>")
        sys.exit(1)
    print(f"使用数据文件: {data_file}")

    # 创建测试请求
    test_request = GenerateChartWithPromptRequest(
        file_paths=[data_file],
        user_prompt="我需要美观且直观的图表",
        model_url=model_url,
        model_type=model_name,
        model_api_key=model_api_key,
        mcp_prompt="",
        skill_prompt=""
    )
    
    print(f"\n测试请求:")
    print(f"  文件路径: {test_request.file_paths}")
    print(f"  用户提示: {test_request.user_prompt}")
    print(f"  模型类型: {test_request.model_type}")
    
    # 获取配置文件路径
    config_path = project_root / "configs" / "default_config.json"
    
    print(f"\n配置文件路径: {config_path}")
    
    try:
        # 调用service_main函数
        print("\n" + "=" * 60)
        print("调用service_main函数...")
        print("=" * 60)
        
        await service_main(test_request, config_path=str(config_path))
        
        print("\n" + "=" * 60)
        print("测试完成！")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n测试出错: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_service_main())
