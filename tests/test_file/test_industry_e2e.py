"""行业场景端到端回归（真实模型）——帕累托 / 主次因素分析。

默认测试集排除 needs_llm；显式运行：

    .venv/Scripts/python.exe -m pytest tests/test_file/test_industry_e2e.py \
        -o addopts="" -m "needs_llm and integration" -q -s

用例按 docs/行业场景扩展规划.md §4.1 设计（业务系统原始导出 + 业务话术 +
业务验收），基准数字见 tests/fixtures/industry/pareto_quality/README.md。

验收口径（业务结果优先，不数 HTML token）：

- 生成代码完成聚合：Bar 数量合计 = 102、降序、11 类目（划伤/表面划伤不合并）；
- Line 累计占比单调不减且终点 ≈ 100；
- 双轴形态（两张叠加或合并后两套 yAxis）、80% 参考线存在。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

# 先导入 service（规避 service ↔ agent 循环导入），再导入 pyecharts 工具
from service.data_ingestion import DataSource, ingest
from service.pipeline.agent_pipeline import run_agent_pipeline

pytestmark = [pytest.mark.needs_llm, pytest.mark.integration]

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "industry" / "pareto_quality" / "defect_log.csv"
USER_PROMPT = "帮我分析这两周SMT产线的不良集中在哪些项目，做一个主次因素排列图"


def _opts_dict(node):
    """pyecharts BasicOpts / dict 统一成 dict。"""
    if isinstance(node, dict):
        return node
    raw = getattr(node, "opts", None)
    return raw if isinstance(raw, dict) else {}


async def test_pareto_defect_analysis_end_to_end(real_agent, tmp_path: Path, monkeypatch):
    profile = await ingest(
        DataSource(kind="file", path=str(FIXTURE), name="SMT不良判定记录")
    )
    model_ = SimpleNamespace(
        user_prompt=USER_PROMPT,
        file_paths=[str(FIXTURE)],
        config=None,
        mcp_prompt="",
        skill_prompt="",
        model_type="deepseek",
    )

    result = await run_agent_pipeline(
        real_agent, model_, profile, tmp_path, task_id=None, max_iterations=18
    )
    logs = result["agent_logs"]
    assert result["successful_charts"], "未产出任何图表:\n" + "\n".join(logs[-10:])

    pareto_charts = [
        chart for chart in result["successful_charts"]
        if str((chart.get("plan") or {}).get("chart_type", "")).lower() in {"bar", "line"}
    ]
    assert pareto_charts, "帕累托应是 Bar 形态: " + "\n".join(logs[-10:])

    # ---------- 业务验收：重放 success 代码，读 chart.options ----------
    code_files = sorted(tmp_path.glob("**/code/*success*.py"))
    assert code_files, f"没有 success 代码: {logs[-10:]}"

    # 沙箱化重放环境：产物临时落 tmp，不污染项目根（注入头按 env 决定 render 路径）
    monkeypatch.setenv("CHART_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("CHART_OUTPUT_NAME", "pareto_replay.html")

    ns: dict = {"__name__": "pareto_e2e", "__file__": str(code_files[0])}
    code_text = code_files[0].read_text(encoding="utf-8")
    exec(compile(code_text, str(code_files[0]), "exec"), ns)
    chart_obj = ns.get("chart") or next(
        (
            v
            for v in ns.values()
            if hasattr(v, "options") and hasattr(v, "render") and not hasattr(v, "__path__")
        ),
        None,
    )
    assert chart_obj is not None, "成功代码应构造 chart 对象"
    opts = chart_obj.options

    series = [node for node in opts.get("series", []) if _opts_dict(node)]
    bar_series = next((s for s in series if str(_opts_dict(s).get("type")) == "bar"), None)
    assert bar_series is not None, [
        (_opts_dict(s).get("type"), _opts_dict(s).get("name")) for s in series
    ]

    # 1) 聚合口径：数量合计 = 102（README 基准），顺序降序
    bar_values = []
    for item in bar_series.get("data", []):
        if isinstance(item, (int, float)):
            bar_values.append(float(item))
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            bar_values.append(float(item[-1]))
    assert len(bar_values) == 11, bar_values
    assert sum(bar_values) == pytest.approx(102), sum(bar_values)
    assert bar_values == sorted(bar_values, reverse=True), bar_values

    # 2) 占比 series 与双轴
    line_series = next(
        (s for s in series
         if str(_opts_dict(s).get("type")) == "line"
         and "占比" in str(_opts_dict(s).get("name") or "")),
        next((s for s in series if str(_opts_dict(s).get("type")) == "line"), None),
    )
    assert line_series is not None, "缺累计占比系列"
    cum_values = [
        float(item[-1]) if isinstance(item, (list, tuple)) and len(item) >= 2 else float(item)
        for item in line_series.get("data", [])
    ]
    assert cum_values == sorted(cum_values), cum_values
    assert cum_values[-1] == pytest.approx(100, abs=0.5), cum_values[-3:]

    y_axes = opts.get("yAxis")
    y_list = y_axes if isinstance(y_axes, list) else [y_axes]
    assert len([a for a in y_list if a]) >= 2, f"应有双轴: {y_axes}"

    # 3) 80% 参考线
    ml = _opts_dict(line_series).get("markLine") or {}
    ml_data = ml.get("data") or []

    def _ml_text(d):
        raw = _opts_dict(d) or getattr(d, "opts", None)
        if not raw:
            return ""
        return " ".join(str(v) for v in raw.values() if v not in (None, ""))

    assert ml_data and any(
        "80" in _ml_text(d) for d in ml_data
    ), str([sorted(getattr(d, "opts", {}).keys()) if hasattr(d, "opts") else d for d in ml_data])[:200]

    # 4) 类目保真：同义类目不合并
    x_axis = opts.get("xAxis")
    x_node = (x_axis[0] if isinstance(x_axis, list) else x_axis) or {}
    x_data = x_node.get("data") or []
    assert x_data and len(x_data) == 11, x_data
    assert "划伤" in x_data and "表面划伤" in x_data, x_data
