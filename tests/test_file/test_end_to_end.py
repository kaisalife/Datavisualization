"""端到端集成测试（真实模型，v4）。

完整跑通：数据文件 -> 语义 series 拆分 -> 计划 agent 会话选 series 产出 plans
-> 逐 plan 生成 pyecharts HTML + 自包含 py。

运行：.venv/Scripts/python.exe -m pytest tests/test_file -o addopts="" -m "needs_llm and integration"
注意：涉及多次真实 LLM 调用（plan agent 会话 + 逐 plan 图表生成），预计 5-10 分钟。
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from service.data_ingestion import DataSource, ingest
from service.pipeline.agent_pipeline import run_agent_pipeline

pytestmark = [pytest.mark.needs_llm, pytest.mark.integration]


async def test_end_to_end(real_agent, normal_csv: Path, tmp_path: Path):
    """完整链路：产物契约 = 非空 HTML + 自包含 py（series 加载）+ plans 含 series_id。"""
    profile = await ingest(DataSource(kind="file", path=str(normal_csv), name="销售数据"))
    assert profile.row_count == 4
    assert profile.series_catalog is not None

    model_ = SimpleNamespace(
        user_prompt="分析销售数据：画两个图，各年份销售额趋势 + 各区域销售额对比",
        file_paths=[str(normal_csv)],
        config=None,
        mcp_prompt="",
        skill_prompt="",
        model_type="deepseek",
    )

    result = await run_agent_pipeline(
        real_agent, model_, profile, tmp_path, task_id=None, max_iterations=18
    )
    logs = result["agent_logs"]

    # 1. 至少一个图表成功，HTML 存在且非空
    assert result["successful_charts"], "未产出任何图表:\n" + "\n".join(logs[-8:])
    for chart in result["successful_charts"]:
        html = Path(chart["chart_path"])
        assert html.exists() and html.stat().st_size > 0
        assert html.read_text(encoding="utf-8").strip().startswith("<!DOCTYPE html>")

    # 2. 产物自包含：注入版 code_*_success.py（series 加载，无 duckdb）
    code_files = sorted((tmp_path / "code").glob("code_*_success.py"))
    assert code_files, "缺少自包含 code_*_success.py"
    for f in code_files:
        src = f.read_text(encoding="utf-8")
        assert "duckdb" not in src
        assert "read_parquet" in src

    # 3. all_plans.json 含 series_id（阶段2 产物）
    plans_data = json.loads((tmp_path / "all_plans.json").read_text(encoding="utf-8"))
    assert plans_data.get("plans"), "all_plans.json 无 plans"
    for p in plans_data["plans"]:
        assert p.get("series_id"), f"plan 缺 series_id: {p}"

    # 4. manifest.json 落盘于会话目录（阶段1 产物）
    assert (Path(profile.session_dir) / "manifest.json").exists()