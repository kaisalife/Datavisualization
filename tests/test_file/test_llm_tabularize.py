"""LLM 表格化集成测试（P2：非表格源 -> 结构化表格，真实模型）。

HTML（div 结构，unstructured 认不出表格）与日志经 LlmTabularReader
用 LLM 抽取为结构化表并注册进 DuckDB，验证多列可读。

运行：.venv/Scripts/python.exe -m pytest tests/test_file -o addopts="" -m "needs_llm and integration"
"""
from __future__ import annotations

from pathlib import Path

import pytest

from service.data_ingestion import DataSource, ingest

pytestmark = [pytest.mark.needs_llm, pytest.mark.integration]


@pytest.fixture
def div_html(tmp_path: Path) -> Path:
    """div 结构数据（无 <table>，unstructured 提取不到表格）。"""
    path = tmp_path / "门店销售.html"
    path.write_text(
        "<html><body><h1>2025 门店销售</h1>\n"
        '<div class="store"><span>北京店</span><span>2025</span><span>1234.5</span></div>\n'
        '<div class="store"><span>上海店</span><span>2025</span><span>980.0</span></div>\n'
        '<div class="store"><span>广州店</span><span>2024</span><span>870.5</span></div>\n'
        "</body></html>",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def sample_log(tmp_path: Path) -> Path:
    """服务日志（每行 时间 级别 模块 user ip）。"""
    path = tmp_path / "server.log"
    path.write_text(
        "2025-06-01 10:00:01 INFO  user_login  user=alice ip=10.0.0.1\n"
        "2025-06-01 10:00:05 ERROR db_timeout  user=bob   ip=10.0.0.2\n"
        "2025-06-01 10:00:09 INFO  user_login  user=carol ip=10.0.0.3\n",
        encoding="utf-8",
    )
    return path


async def test_llm_tabularize_div_html(div_html: Path):
    """div 结构 HTML：LLM 抽取出门店销售结构化表（多列可读）。"""
    profile = await ingest(DataSource(kind="file", path=str(div_html), name="门店销售"))
    cols = {c["name"] for c in profile.schema}
    # LLM 抽取出的表：至少含门店/数值类列，且行数>0
    assert len(cols) >= 2
    assert profile.row_count >= 2
    # 能读到真实值（series 加载）
    catalog = profile.series_catalog
    assert catalog is not None and catalog.series
    series = catalog.series[0]
    from service.data_ingestion.series import load_series_df
    df = load_series_df(series)
    assert len(df) >= 2


async def test_llm_tabularize_log(sample_log: Path):
    """日志：LLM 抽取为 时间/级别/模块/user/ip 结构化表。"""
    profile = await ingest(DataSource(kind="file", path=str(sample_log), name="服务日志"))
    cols = {c["name"] for c in profile.schema}
    # 关键列被识别（日志语义列）
    assert "级别" in cols or "level" in cols or "user" in cols
    assert profile.row_count >= 3
