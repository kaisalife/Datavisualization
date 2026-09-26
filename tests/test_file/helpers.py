"""数据预览全流程集成测试的共享逻辑（v4，无 DuckDB）。

run_preview_fullflow: 数据文件 -> ingestion -> 语义 series 落盘 -> 返回中间产物供断言。
"""
from __future__ import annotations

from pathlib import Path

from service.data_ingestion import DataSource, ingest
from service.data_ingestion.series import load_series_df


async def run_preview_fullflow(file_path: Path, task_dir: Path, chat=None) -> dict:
    """跑一遍数据预览全流程（v4）。

    Args:
        file_path: 数据文件
        task_dir: 落盘目录（保留签名；v4 无 AI recipe 生成）
        chat: 兼容旧签名，v4 不再使用

    Returns:
        {"profile","catalog","n_series","session_dir","series"}
    """
    source = DataSource(kind="file", path=str(file_path), name=file_path.stem)
    profile = await ingest(source)
    catalog = profile.series_catalog
    return {
        "profile": profile,
        "catalog": catalog,
        "n_series": len(catalog.series) if catalog else 0,
        "session_dir": Path(profile.session_dir) if profile.session_dir else None,
        "series": catalog.series if catalog else [],
    }


def assert_artifacts(result: dict) -> None:
    """落盘产物契约（v4）：manifest.json + 每个 series .parquet 可读非空。"""
    profile = result["profile"]
    session_dir = Path(profile.session_dir)
    assert session_dir.exists(), "会话目录不存在"
    manifest = session_dir / "manifest.json"
    assert manifest.exists(), f"缺少 manifest.json: {manifest}"

    catalog = result["catalog"]
    assert catalog is not None and catalog.series, "series 目录为空"
    for s in catalog.series:
        df = load_series_df(s)
        assert len(df) > 0, f"series 为空: {s.series_id}"
        assert Path(s.data_path).exists(), f"series parquet 缺失: {s.data_path}"