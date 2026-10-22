"""单图二次优化端到端回归（真实模型）：改标题/图例 → 只跑优化 agent。

默认测试集排除 needs_llm；显式运行：

    .venv/Scripts/python.exe -m pytest tests/test_file/test_chart_optimize_e2e.py \
        -o addopts="" -m "needs_llm and integration" -q -s

验收口径（docs/my-需求 二次优化线第 4 步）：

- 输入是「已成功的图表」三件套：plan JSON + 注入版自包含代码 + series parquet；
- 优化 agent 只改图形实现（标题/图例/配色/Top-N），数据读取由守护层重新注入；
- 原代码/原图永不覆盖（code_p1_opt1_success.py 新文件）；
- 优化后 HTML 校验 + 数据检查通过（与首次生成同一套校验）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

# 先导入 service（规避 service ↔ agent 循环导入，agent fixture 依赖已知状态）
from service.pipeline.chart_optimizer import optimize_single_chart
from service.pipeline.optimize_flow import _strip_injection_header

pytestmark = [pytest.mark.needs_llm, pytest.mark.integration]

NEW_TITLE = "2024年净销售额趋势"


@pytest.fixture
def optimize_workspace(tmp_path: Path) -> dict:
    """已成功图表的三件套工作区（模拟 generate_single_chart 的产物布局）。"""
    import pandas as pd

    from service.data_ingestion.series.models import SemanticSeries
    from service.data_ingestion.series.snippet import series_snippet

    out = tmp_path / "workspace" / "月度销售数据"
    for sub in ("plans", "code", "charts"):
        (out / sub).mkdir(parents=True)

    data_file = tmp_path / "月度销售额.parquet"
    pd.DataFrame({
        "月份": [f"{m}月" for m in range(1, 13)],
        "销售额": [820.0, 940.0, 1105.0, 990.0, 1230.0, 1310.0,
                   1190.0, 1420.0, 1380.0, 1505.0, 1610.0, 1750.0],
    }).to_parquet(data_file)

    series = SemanticSeries(
        series_id="月度销售额",
        name="月度销售额趋势",
        axis_kind="time_series",
        row_label_column="月份",
        column_label_columns=["销售额"],
        data_path=str(data_file),
        source_table="月度销售数据",
    )
    plan = {
        "plan_id": "p1",
        "plan_name": "月度销售额趋势",
        "chart_title": "月度销售额",
        "chart_type": "Line",
        "series_id": "月度销售额",
        "x_axis": "月份",
        "y_axis": ["销售额"],
        "analysis_goal": "展示 2024 年销售额的逐月走势",
        "data_interface": {
            "columns": ["月份", "销售额"],
            "time_like": ["月份"],
            "measures": ["销售额"],
        },
    }
    (out / "plans" / "plan_p1.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 注入版自包含代码：注入段 + "LLM 写的" 绘图代码（与生成产物同构）
    llm_code = """import pyecharts.options as opts
from pyecharts.charts import Line

line = Line(init_opts=opts.InitOpts(width="900px", height="500px"))
line.add_xaxis(df["月份"].tolist())
line.add_yaxis("销售额", df["销售额"].round(1).tolist(), is_symbol_show=False)
line.set_global_opts(
    title_opts=opts.TitleOpts(title="月度销售额", pos_left="center"),
    xaxis_opts=opts.AxisOpts(name="月份"),
    yaxis_opts=opts.AxisOpts(name="销售额"),
)
line.render()
"""
    code_file = out / "code" / "code_p1_success.py"
    code_file.write_text(
        series_snippet(series) + "\n" + llm_code, encoding="utf-8"
    )

    return {
        "output_folder": out,
        "plan": plan,
        "code_file": code_file,
        "data_path": str(data_file),
        "ii": "unused",
    }


@pytest.mark.asyncio
async def test_optimize_real_model(real_agent, optimize_workspace: dict):
    ws = optimize_workspace
    original_raw = ws["code_file"].read_text(encoding="utf-8")
    original_code = _strip_injection_header(original_raw)

    ok, chart_path, code, plan_id, err = await optimize_single_chart(
        real_agent,
        user_prompt=(
            f"把图表标题改成「{NEW_TITLE}」，"
            "并把图例移到图表下方、给折线加上每个点的数据标签。"
        ),
        plan=ws["plan"],
        original_code=original_code,
        chart_id="chart_p1_20260101_000000.html",
        data_path=ws["data_path"],
        output_folder=Path(ws["output_folder"]),
        dataset_summary='{"rows": 12, "columns": [{"name": "月份", "type": "object"}, {"name": "销售额", "type": "float64"}]}',
    )

    assert ok, f"优化失败: {err}"
    assert plan_id == "p1_opt1"
    html = Path(chart_path).read_text(encoding="utf-8")
    # pyecharts 会把中文序列化成 \uXXXX 转义，两种形式都接受
    escaped_title = json.dumps(NEW_TITLE, ensure_ascii=True)[1:-1]
    assert (NEW_TITLE in html) or (escaped_title in html), "新标题未生效"
    # 原代码永不覆盖
    assert ws["code_file"].read_text(encoding="utf-8") == original_raw
    # 优化产物落盘且为注入版自包含代码
    opt_code_file = ws["output_folder"] / "code" / "code_p1_opt1_success.py"
    assert opt_code_file.is_file()
    opt_code = opt_code_file.read_text(encoding="utf-8")
    assert "# --- series:" in opt_code and "# --- end series ---" in opt_code
    assert (NEW_TITLE in opt_code) or (escaped_title in opt_code)
