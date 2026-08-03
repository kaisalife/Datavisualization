"""端到端验证：文件源 → adapter → primary_data_path 是否可读。

回归测试：确认 M1 之后文件源仍然能被下游正确消费。
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from service.viz_data.adapters.file_adapter import FileAdapter
from agent_tools.sandbox import run_python_safely


async def main():
    adapter = FileAdapter(["test_env/data_files/季度数据.csv"])
    ds = await adapter.adapt(engine=None)

    parquet_path = ds.primary_data_path()
    # 使用绝对路径（真实场景 app.py 传的是 upload 目录绝对路径）
    original_csv = str(Path("test_env/data_files/季度数据.csv").resolve())

    print(f"parquet_path = {parquet_path}")
    print(f"original_csv = {original_csv}")

    # M1 中 file_test 仍是原 CSV，chart_generator 传给 LLM 的还是 CSV。
    # 验证 LLM 生成的代码若用 read_csv 或 read_parquet 都能跑。
    charts_dir = (Path(__file__).parent / "_charts_file_smoke").resolve()
    charts_dir.mkdir(exist_ok=True)
    charts_dir_str = str(charts_dir).replace("\\", "/")

    # 场景 A：读 CSV
    code_csv = f'''
import pandas as pd
from pyecharts.charts import Line
from pyecharts import options as opts

df = pd.read_csv(r"{original_csv}")
print("A(csv) 读取:", df.shape)

# 用列名（对齐 planner 输出）
x = sorted(df["季度"].unique().tolist())
line = Line()
line.add_xaxis(x)
for prod in sorted(df["产品线"].unique().tolist()):
    sub = df[df["产品线"] == prod].sort_values("季度")
    line.add_yaxis(prod, sub["销售额(万元)"].tolist())
line.set_global_opts(title_opts=opts.TitleOpts(title="各产品线季度销售额"))
line.render(r"{charts_dir_str}/chart_file_csv.html")
print("A 完成")
'''

    # 场景 B：读 parquet
    parquet_path_str = parquet_path.replace("\\", "/") if parquet_path else ""
    code_parquet = f'''
import pandas as pd
from pyecharts.charts import Line
from pyecharts import options as opts

df = pd.read_parquet(r"{parquet_path_str}", engine="pyarrow")
print("B(parquet) 读取:", df.shape)

x = sorted(df["季度"].unique().tolist())
line = Line()
line.add_xaxis(x)
for prod in sorted(df["产品线"].unique().tolist()):
    sub = df[df["产品线"] == prod].sort_values("季度")
    line.add_yaxis(prod, sub["销售额(万元)"].tolist())
line.set_global_opts(title_opts=opts.TitleOpts(title="各产品线季度销售额(from parquet)"))
line.render(r"{charts_dir_str}/chart_file_parquet.html")
print("B 完成")
'''

    for name, code in [("csv 路径", code_csv), ("parquet 路径", code_parquet)]:
        print(f"\n=== 场景 {name} ===")
        result = run_python_safely(code, cwd=str(charts_dir), timeout=30)
        print("success:", result.success)
        print("stdout:", result.stdout[:200])
        if not result.success:
            print("stderr:", result.stderr[:400])

    ds.cleanup()

    a = charts_dir / "chart_file_csv.html"
    b = charts_dir / "chart_file_parquet.html"
    print()
    print(f"chart_file_csv.html     exists={a.exists()} size={a.stat().st_size if a.exists() else 0}")
    print(f"chart_file_parquet.html exists={b.exists()} size={b.stat().st_size if b.exists() else 0}")

    assert a.exists(), "CSV 路径链路失败"
    assert b.exists(), "Parquet 路径链路失败"
    print("\n✅ 文件源双路径（CSV/Parquet）都能被沙箱执行并生成图表")


if __name__ == "__main__":
    asyncio.run(main())
