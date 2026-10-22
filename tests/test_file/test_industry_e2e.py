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


# ---------------------------------------------------------------------------
# KPI 仪表盘场景
# ---------------------------------------------------------------------------

GAUGE_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures" / "industry" / "gauge_kpi" / "wind_kpi_log.csv"
)
GAUGE_PROMPT = "3 号机组这个月发电量完成情况怎么样，有没有达标"


def _series_nodes(opts: dict) -> list[dict]:
    return [node for node in opts.get("series", []) if _opts_dict(node)]


def _series_values(series: dict) -> list[float]:
    values = []
    for item in series.get("data", []):
        if isinstance(item, bool):
            continue
        if isinstance(item, (int, float)):
            values.append(float(item))
        elif isinstance(item, (list, tuple)) and len(item) >= 2 and item[-1] is not None:
            values.append(float(item[-1]))
        elif isinstance(item, dict) and isinstance(item.get("value"), (int, float)):
            values.append(float(item["value"]))
    return values


def _replay_chart_options(code_files: list[Path], tmp_path: Path, tag: str) -> list[dict]:
    """重放所有 success 代码，返回每个可执行代码产出的 chart.options。"""
    options: list[dict] = []
    for index, code_file in enumerate(code_files):
        os.environ["CHART_OUTPUT_DIR"] = str(tmp_path)
        os.environ["CHART_OUTPUT_NAME"] = f"{tag}_{index}.html"
        ns: dict = {"__name__": f"{tag}_{index}", "__file__": str(code_file)}
        code_text = code_file.read_text(encoding="utf-8")
        exec(compile(code_text, str(code_file), "exec"), ns)
        chart_obj = ns.get("chart") or next(
            (
                value
                for value in ns.values()
                if hasattr(value, "options") and hasattr(value, "render")
                and not hasattr(value, "__path__")
            ),
            None,
        )
        if chart_obj is not None:
            options.append(chart_obj.options)
    return options


async def test_gauge_kpi_snapshot_end_to_end(real_agent, tmp_path: Path):
    profile = await ingest(
        DataSource(kind="file", path=str(GAUGE_FIXTURE), name="风电场月度考核")
    )
    model_ = SimpleNamespace(
        user_prompt=GAUGE_PROMPT,
        file_paths=[str(GAUGE_FIXTURE)],
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

    gauge_charts = [
        chart for chart in result["successful_charts"]
        if str((chart.get("plan") or {}).get("chart_type", "")).lower() == "gauge"
    ]
    assert gauge_charts, "单机组达标语义应选 Gauge: " + "\n".join(logs[-10:])

    code_files = sorted(tmp_path.glob("**/code/*success*.py"))
    assert code_files, f"没有 success 代码: {logs[-10:]}"
    all_options = _replay_chart_options(code_files, tmp_path, "gauge_replay")

    gauge = next(
        (
            series_node
            for opts in all_options
            for series_node in _series_nodes(opts)
            if str(_opts_dict(series_node).get("type")) == "gauge"
        ),
        None,
    )
    assert gauge is not None, "成功代码里没有 gauge series"

    values = _series_values(gauge)
    # 业务基准：1824 / 1900 = 96.0%，允许 1 位小数以内的生成差异
    assert any(abs(value - 96.0) <= 0.6 for value in values), values
    assert float(gauge.get("max") or 0) >= 100

    detail = _opts_dict(gauge.get("detail")) or {}
    assert "%" in str(detail.get("formatter") or ""), detail


# ---------------------------------------------------------------------------
# SPC 过程稳定性场景
# ---------------------------------------------------------------------------

SPC_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures" / "industry" / "spc_stability" / "coating_thickness.csv"
)
SPC_PROMPT = "涂布一线的极片面密度这一个月稳不稳定？有没有超出控制限的点，帮我做个控制图看看"


async def test_spc_control_chart_end_to_end(real_agent, tmp_path: Path):
    profile = await ingest(
        DataSource(kind="file", path=str(SPC_FIXTURE), name="极片涂布面密度")
    )
    model_ = SimpleNamespace(
        user_prompt=SPC_PROMPT,
        file_paths=[str(SPC_FIXTURE)],
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

    line_charts = [
        chart for chart in result["successful_charts"]
        if str((chart.get("plan") or {}).get("chart_type", "")).lower() in {"line", "area"}
    ]
    assert line_charts, "SPC 应是 Line 形态: " + "\n".join(logs[-10:])

    code_files = sorted(tmp_path.glob("**/code/*success*.py"))
    all_options = _replay_chart_options(code_files, tmp_path, "spc_replay")

    line_pair = next(
        (
            (opts, series_node)
            for opts in all_options
            for series_node in _series_nodes(opts)
            if str(_opts_dict(series_node).get("type")) == "line"
        ),
        None,
    )
    assert line_pair is not None, "成功代码里没有 line series"
    line_options, line_series = line_pair

    series_dict = _opts_dict(line_series)
    # 1) 三条控制限（CL / UCL / LCL），数值与 README 基准一致（±0.06）
    marklines = _opts_dict(series_dict.get("markLine")) or {}
    mark_values = []
    for item in marklines.get("data") or []:
        raw = _opts_dict(item)
        value = raw.get("yAxis", raw.get("y"))
        if isinstance(value, (int, float)):
            mark_values.append(float(value))
    assert len(mark_values) >= 3, mark_values
    assert any(abs(v - 20.0403) <= 0.06 for v in mark_values), mark_values  # CL
    assert any(abs(v - 20.1705) <= 0.06 for v in mark_values), mark_values  # UCL
    assert any(abs(v - 19.9102) <= 0.06 for v in mark_values), mark_values  # LCL

    # 2) 超限点用 markPoint 标出（至少 2 个，数据里实际 3 个）
    markpoints = _opts_dict(series_dict.get("markPoint")) or {}
    point_items = [item for item in (markpoints.get("data") or []) if _opts_dict(item)]
    assert len(point_items) >= 2, len(point_items)
    coords = [_opts_dict(item).get("coord") for item in point_items]
    assert all(isinstance(coord, (list, tuple)) and len(coord) == 2 for coord in coords), coords

    # 3) 缺失值不插值：29 个有效观测（时间轴 29 或 30 个类目）
    values = _series_values(series_dict)
    assert len(values) == 29, len(values)

    x_axis = line_options.get("xAxis")
    x_node = (x_axis[0] if isinstance(x_axis, list) else x_axis) or {}
    x_data = x_node.get("data") or []
    assert 29 <= len(x_data) <= 30, x_data
