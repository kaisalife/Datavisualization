"""PDF 跨页续表合并回归（假视觉模型，不联网）。"""
from __future__ import annotations

import pandas as pd
import pytest

import service.data_ingestion.readers.multimodal_reader as mr
from service.data_ingestion.readers.multimodal_reader import MultimodalReader


def _run_pdf(tmp_path, frames, monkeypatch, *, multi_table: bool = False):
    pdf_path = tmp_path / "report.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")

    monkeypatch.setattr(
        mr,
        "_pdf_page_data_urls",
        lambda path, max_pages: ["data:image/png;base64,x"] * len(frames),
    )
    iterator = iter(frames)

    def fake_extract(llm, image_url, hint="", multi_table=False, **kwargs):
        return next(iterator)

    monkeypatch.setattr(mr, "extract_tables_from_image", fake_extract)
    return MultimodalReader.read(
        str(pdf_path), llm=object(), max_pages=len(frames), multi_table=multi_table
    )


def test_time_continuation_merges_across_pages(tmp_path, monkeypatch):
    page1 = pd.DataFrame(
        {
            "日期": ["2024-01-01", "2024-01-02", "2024-01-03"],
            "销售额": [10, 20, 30],
        }
    )
    page2 = pd.DataFrame(
        {
            "日期": ["2024-01-04", "2024-01-05"],
            "销售额": [40, 50],
        }
    )

    tables = _run_pdf(tmp_path, [[page1], [page2]], monkeypatch)

    assert len(tables) == 1
    table = tables[0]
    assert table.name == "report"
    assert table.source_path.endswith("#page1-2")
    assert table.df["日期"].tolist() == [
        "2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05",
    ]
    assert table.df["销售额"].tolist() == [10, 20, 30, 40, 50]


def test_three_page_time_continuation_merges_once(tmp_path, monkeypatch):
    frames = [
        [pd.DataFrame({"日期": ["2024-01-01", "2024-01-02"], "销售额": [1, 2]})],
        [pd.DataFrame({"日期": ["2024-01-03", "2024-01-04"], "销售额": [3, 4]})],
        [pd.DataFrame({"日期": ["2024-01-05"], "销售额": [5]})],
    ]

    tables = _run_pdf(tmp_path, frames, monkeypatch)

    assert len(tables) == 1
    assert len(tables[0].df) == 5
    assert tables[0].source_path.endswith("#page1-3")


def test_monthly_snapshot_tables_are_not_merged(tmp_path, monkeypatch):
    page1 = pd.DataFrame({"月份": ["2024-01", "2024-01"], "销售额": [10, 20]})
    page2 = pd.DataFrame({"月份": ["2024-02", "2024-02"], "销售额": [30, 40]})

    tables = _run_pdf(tmp_path, [[page1], [page2]], monkeypatch)

    assert len(tables) == 2
    assert [table.name for table in tables] == ["report_p1", "report_p2"]
    assert len(tables[0].df) == 2 and len(tables[1].df) == 2


def test_time_column_need_not_be_first(tmp_path, monkeypatch):
    page1 = pd.DataFrame(
        {"城市": ["北京", "上海"], "月份": ["2024-01", "2024-02"], "销售额": [10, 20]}
    )
    page2 = pd.DataFrame(
        {"城市": ["北京", "上海"], "月份": ["2024-03", "2024-04"], "销售额": [30, 40]}
    )

    tables = _run_pdf(tmp_path, [[page1], [page2]], monkeypatch)

    assert len(tables) == 1
    assert tables[0].df["月份"].tolist() == [
        "2024-01", "2024-02", "2024-03", "2024-04",
    ]


def test_time_reset_is_not_merged(tmp_path, monkeypatch):
    page1 = pd.DataFrame({"日期": ["2024-01-01", "2024-01-02"], "销售额": [1, 2]})
    page2 = pd.DataFrame({"日期": ["2024-01-01", "2024-01-02"], "销售额": [1, 2]})

    tables = _run_pdf(tmp_path, [[page1], [page2]], monkeypatch)

    assert len(tables) == 2


def test_non_time_table_merges_only_on_duplicate_boundary_row(tmp_path, monkeypatch):
    page1 = pd.DataFrame({"城市": ["北京", "上海"], "销售额": [10, 20]})
    page2 = pd.DataFrame({"城市": ["上海", "广州"], "销售额": [20, 30]})

    tables = _run_pdf(tmp_path, [[page1], [page2]], monkeypatch)

    assert len(tables) == 1
    assert tables[0].name == "report"
    assert tables[0].df["城市"].tolist() == ["北京", "上海", "广州"]
    assert tables[0].df["销售额"].tolist() == [10, 20, 30]


def test_non_time_table_without_boundary_overlap_is_not_merged(tmp_path, monkeypatch):
    page1 = pd.DataFrame({"城市": ["北京", "上海"], "销售额": [10, 20]})
    page2 = pd.DataFrame({"城市": ["广州", "深圳"], "销售额": [30, 40]})

    tables = _run_pdf(tmp_path, [[page1], [page2]], monkeypatch)

    assert len(tables) == 2


def test_total_row_blocks_merge(tmp_path, monkeypatch):
    page1 = pd.DataFrame({"城市": ["北京", "合计"], "销售额": [10, 10]})
    page2 = pd.DataFrame({"城市": ["上海"], "销售额": [20]})

    tables = _run_pdf(tmp_path, [[page1], [page2]], monkeypatch)

    assert len(tables) == 2


def test_different_columns_are_not_merged(tmp_path, monkeypatch):
    page1 = pd.DataFrame({"日期": ["2024-01-01"], "销售额": [10]})
    page2 = pd.DataFrame({"日期": ["2024-01-02"], "利润": [3]})

    tables = _run_pdf(tmp_path, [[page1], [page2]], monkeypatch)

    assert len(tables) == 2


def test_multi_table_pages_are_not_merged(tmp_path, monkeypatch):
    frames = [
        [
            pd.DataFrame({"日期": ["2024-01-01"], "销售额": [1]}),
            pd.DataFrame({"日期": ["2024-01-01"], "利润": [2]}),
        ],
        [pd.DataFrame({"日期": ["2024-01-02"], "销售额": [3]})],
    ]

    tables = _run_pdf(tmp_path, frames, monkeypatch, multi_table=True)

    assert len(tables) == 3
    assert [table.name for table in tables] == [
        "report_p1_t1", "report_p1_t2", "report_p2",
    ]


def test_merged_table_is_capped_at_max_rows(tmp_path, monkeypatch):
    page1 = pd.DataFrame(
        {
            "日期": [f"2024-01-{day:02d}" for day in range(1, 151)],
            "销售额": list(range(150)),
        }
    )
    page2 = pd.DataFrame(
        {
            "日期": [f"2024-02-{day:02d}" for day in range(1, 151)],
            "销售额": list(range(150)),
        }
    )

    tables = _run_pdf(tmp_path, [[page1], [page2]], monkeypatch)

    assert len(tables) == 1
    assert len(tables[0].df) == mr._MAX_ROWS
