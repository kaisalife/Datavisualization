"""端到端生产冒烟测试

用样例 CSV 跑通完整链路：
- app.py 日志配置
- QueryEngine（budget/compact/cost/logging）
- 沙箱代码执行
- 图表 HTML 输出

用法：
    python test_env/e2e_smoke_test.py
    python test_env/e2e_smoke_test.py <数据文件路径>
    python test_env/e2e_smoke_test.py <数据文件路径> "<用户需求>"

环境变量：
    TEST_DATA_FILE    数据文件路径（默认 test_env/data_files/季度数据.csv）
    MODEL_NAME / BASE_URL / API_KEY   模型配置（新）
    MODEL_NAME_KIMI2.5 / BASE_URL_WWCQ / API_KEY_WWCQ  模型配置（旧名，兼容）
    LOG_PATH          日志文件路径（默认 logs/e2e_test.jsonl）
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

from dotenv import load_dotenv

# 优先加载 test_env/.env，再加载项目根 .env
load_dotenv(Path(__file__).parent / ".env")
load_dotenv(project_root / ".env")

# 提前配置日志到测试专用文件
os.environ.setdefault("LOG_PATH", "logs/e2e_test.jsonl")
os.environ.setdefault("LOG_LEVEL", "INFO")

from service.observability.logger import configure_logging, get_logger
configure_logging(log_path=os.environ["LOG_PATH"], level=os.environ["LOG_LEVEL"])
logger = get_logger("e2e_test")

from Entity.ApiModels import GenerateChartWithPromptRequest
from service.service_main import service_main


def _get_default_data_file() -> str:
    return str(project_root / "test_env" / "data_files" / "季度数据.csv")


def _parse_args():
    data_file = None
    user_prompt = "我需要美观且直观的图表，展示各产品线的季度表现趋势"

    if len(sys.argv) >= 2:
        data_file = sys.argv[1]
    if len(sys.argv) >= 3:
        user_prompt = sys.argv[2]

    if not data_file:
        data_file = os.getenv("TEST_DATA_FILE", _get_default_data_file())

    return data_file, user_prompt


async def run_test():
    print("=" * 70)
    print("端到端生产冒烟测试（DataVisualServer）")
    print("=" * 70)

    data_file, user_prompt = _parse_args()

    if not Path(data_file).exists():
        print(f"❌ 数据文件不存在: {data_file}")
        sys.exit(1)

    model_name = os.getenv("MODEL_NAME") or os.getenv("MODEL_NAME_KIMI2.5", "kimi2.5")
    model_url = os.getenv("BASE_URL") or os.getenv("BASE_URL_WWCQ", "https://open.bigmodel.cn/api/paas/v4/")
    api_key = os.getenv("API_KEY") or os.getenv("API_KEY_WWCQ", "")

    print(f"数据文件: {data_file}")
    print(f"用户需求: {user_prompt}")
    print(f"模型: {model_name}")
    print(f"URL:  {model_url}")
    print(f"API Key: {'已配置' if api_key else '❌ 未配置（会失败）'}")
    print(f"日志文件: {os.environ['LOG_PATH']}")
    print("=" * 70)

    if not api_key:
        print("❌ 缺少 API_KEY 环境变量（或旧名 API_KEY_WWCQ），无法调用真实模型")
        sys.exit(2)

    logger.info("e2e_test_start", data_file=data_file, model=model_name)

    request = GenerateChartWithPromptRequest(
        file_paths=[data_file],
        user_prompt=user_prompt,
        model_url=model_url,
        model_type=model_name,
        model_api_key=api_key,
        mcp_prompt="",
        skill_prompt="",
    )

    config_path = project_root / "configs" / "default_config.json"

    t0 = time.time()
    try:
        result = await service_main(request, config_path=str(config_path))
    except Exception as e:
        logger.error("e2e_test_exception", error=str(e), error_type=type(e).__name__)
        import traceback
        traceback.print_exc()
        sys.exit(3)

    duration = time.time() - t0

    successful = result.get("successful_charts", []) if isinstance(result, dict) else []
    failed = result.get("failed_plans", []) if isinstance(result, dict) else []

    print("\n" + "=" * 70)
    print(f"测试完成，用时 {duration:.2f}s")
    print(f"✅ 成功图表: {len(successful)}")
    for item in successful:
        print(f"  - [{item.get('plan', {}).get('chart_type', '?')}] {item.get('chart_path', '?')}")
    print(f"❌ 失败计划: {len(failed)}")
    for item in failed:
        print(f"  - [{item.get('plan', {}).get('chart_type', '?')}] {item.get('error', '?')[:100]}")
    print("=" * 70)

    logger.info(
        "e2e_test_end",
        duration_seconds=round(duration, 2),
        successful=len(successful),
        failed=len(failed),
    )

    # 断言至少产出一张图表
    if not successful:
        print("❌ 测试失败：未产出任何图表")
        sys.exit(4)

    # 验证图表文件真实存在
    for item in successful:
        chart_path = item.get("chart_path")
        if chart_path and not Path(chart_path).exists():
            print(f"❌ 图表文件缺失: {chart_path}")
            sys.exit(5)

    # 打印日志摘要
    log_path = Path(os.environ["LOG_PATH"])
    if log_path.exists():
        events = {}
        with open(log_path, "r", encoding="utf-8") as lf:
            for line in lf:
                try:
                    evt = json.loads(line).get("event", "?")
                    events[evt] = events.get(evt, 0) + 1
                except Exception:
                    pass
        print("\n日志事件统计:")
        for evt, cnt in sorted(events.items(), key=lambda x: -x[1]):
            print(f"  {evt}: {cnt}")

    print("\n🎉 端到端冒烟测试通过")


if __name__ == "__main__":
    asyncio.run(run_test())
