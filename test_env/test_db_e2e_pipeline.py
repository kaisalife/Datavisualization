"""端到端验证：数据库源 → parquet → 沙箱执行 → HTML 图表。"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from service.viz_data.adapters.database_adapter import DatabaseAdapter
from agent_tools.sandbox import run_python_safely


async def main():
    adapter = DatabaseAdapter(
        db_config={
            "db_type": "sqlite",
            "database": "test_env/databases/sample.db",
            "query": "SELECT r.name AS region, SUM(s.amount) AS total FROM sales s JOIN regions r ON s.region_id=r.id GROUP BY r.name",
        },
        user_prompt="按地区展示销售额",
    )
    ds = await adapter.adapt(engine=None)
    parquet_path = ds.primary_data_path().replace("\\", "/")

    charts_dir = (Path(__file__).parent / "_charts_db_smoke").resolve()
    charts_dir.mkdir(exist_ok=True)
    charts_dir_str = str(charts_dir).replace("\\", "/")

    # 模拟 LLM 按新 prompt 生成的图表代码
    code = f'''
import pandas as pd
from pyecharts.charts import Bar
from pyecharts import options as opts

df = pd.read_parquet(r"{parquet_path}", engine="pyarrow")
print("读取成功:", df.shape)
print(df)

x = df["region"].tolist()
y = df["total"].tolist()

bar = Bar()
bar.add_xaxis(x)
bar.add_yaxis("销售额", y)
bar.set_global_opts(title_opts=opts.TitleOpts(title="各地区销售额"))
bar.render(r"{charts_dir_str}/chart_db_test.html")
print("渲染完成")
'''

    print("=== 执行代码 ===")
    result = run_python_safely(code, cwd=str(charts_dir), timeout=30)
    print("success:", result.success)
    print("stdout:", result.stdout)
    print("stderr:", result.stderr[:500] if result.stderr else "")
    print("error:", result.error)

    html_path = charts_dir / "chart_db_test.html"
    print("图表文件存在:", html_path.exists(),
          "大小:", html_path.stat().st_size if html_path.exists() else 0)

    ds.cleanup()

    assert result.success, "沙箱执行失败"
    assert html_path.exists(), "HTML 未生成"
    assert html_path.stat().st_size > 1000, "HTML 大小异常"
    print("\n✅ 数据库源 → parquet → 沙箱 → HTML 全链路通过")


if __name__ == "__main__":
    asyncio.run(main())
