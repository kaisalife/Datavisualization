"""数据预览 CSV/ZIP 导出回归（不调用 LLM）。"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from service.data_ingestion.series.models import SemanticSeries, SeriesCatalog
from service.data_ingestion.series.splitter import write_manifest
from service.data_ingestion.series_manager import allocate_session_dir


@pytest.fixture
def client(monkeypatch, tmp_path: Path):
    """真实 app + 隔离的 uploads/datasets 目录。"""
    import app as app_module

    uploads = tmp_path / "uploads"
    uploads.mkdir()
    monkeypatch.setenv("TEMP_UPLOAD_DIR", str(uploads))
    monkeypatch.setenv("TEMP_DATASETS_DIR", str(tmp_path / "datasets"))
    old_upload = app_module.app.config["_UPLOAD_DIR"]
    app_module.app.config["_UPLOAD_DIR"] = uploads
    try:
        yield app_module.app.test_client()
    finally:
        app_module.app.config["_UPLOAD_DIR"] = old_upload


def _make_session() -> tuple[str, Path]:
    """建一个含两条 series 的会话目录。"""
    session_id, session_dir = allocate_session_dir()

    sales = pd.DataFrame({"城市": ["北京", "上海"], "销售额": [1200, 1300]})
    sales_path = session_dir / "sales.城市.parquet"
    sales.to_parquet(sales_path, index=False)

    trend = pd.DataFrame({"年份": [2023, 2024], "值": [10, 12]})
    trend_path = session_dir / "trend.值.parquet"
    trend.to_parquet(trend_path, index=False)

    catalog = SeriesCatalog(
        datasets_dir=str(session_dir),
        series=[
            SemanticSeries(
                series_id="sales.城市",
                name="城市",
                axis_kind="categorical_comparison",
                row_label_column="城市",
                column_label_columns=["销售额"],
                data_path=str(sales_path),
                source_table="sales",
            ),
            SemanticSeries(
                series_id="trend.值",
                name="值",
                axis_kind="time_series",
                row_label_column="年份",
                column_label_columns=["值"],
                data_path=str(trend_path),
                source_table="trend",
            ),
        ],
    )
    write_manifest(catalog, session_dir)
    return session_id, session_dir


def test_export_single_series_as_csv(client):
    session_id, _ = _make_session()

    resp = client.get(
        "/api/data-profile/export",
        query_string={"session_id": session_id, "series_id": "sales.城市"},
    )

    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"
    text = resp.data.decode("utf-8-sig")
    assert text.splitlines()[0] == "城市,销售额"
    assert "北京,1200" in text
    disposition = resp.headers["Content-Disposition"]
    assert "attachment" in disposition
    assert "filename*=UTF-8''" in disposition


def test_export_all_series_as_zip(client):
    session_id, _ = _make_session()

    resp = client.get(
        "/api/data-profile/export", query_string={"session_id": session_id}
    )

    assert resp.status_code == 200
    assert resp.mimetype == "application/zip"
    with zipfile.ZipFile(io.BytesIO(resp.data)) as archive:
        names = set(archive.namelist())
        assert names == {"sales.城市.csv", "trend.值.csv"}
        sales_csv = archive.read("sales.城市.csv").decode("utf-8-sig")
        assert "北京,1200" in sales_csv


def test_invalid_session_and_unknown_series_are_404(client, tmp_path: Path):
    assert client.get(
        "/api/data-profile/export", query_string={"session_id": "../etc"}
    ).status_code == 400
    assert client.get(
        "/api/data-profile/export", query_string={"session_id": "ds_000000000000"}
    ).status_code == 404

    session_id, _ = _make_session()
    assert client.get(
        "/api/data-profile/export",
        query_string={"session_id": session_id, "series_id": "no.such"},
    ).status_code == 404


def test_series_path_outside_session_is_refused(client, tmp_path: Path):
    session_id, session_dir = _make_session()
    secret = tmp_path / "secret.parquet"
    pd.DataFrame({"secret": [1]}).to_parquet(secret, index=False)

    catalog = SeriesCatalog.from_manifest(str(session_dir))
    catalog.series[0].data_path = str(secret)
    write_manifest(catalog, session_dir)

    resp = client.get(
        "/api/data-profile/export",
        query_string={"session_id": session_id, "series_id": catalog.series[0].series_id},
    )

    assert resp.status_code == 404


def test_upload_filename_cannot_escape_upload_dir(client, tmp_path: Path):
    source = tmp_path / "source" / "evil.csv"
    source.parent.mkdir()
    source.write_text("城市,销售额\n北京,1200\n", encoding="utf-8")

    with open(source, "rb") as fh:
        resp = client.post(
            "/api/data-profile",
            data={"files": (fh, "../evil.csv")},
            content_type="multipart/form-data",
        )

    assert resp.status_code == 200
    # 不能被写到 uploads 的上一级
    assert not (tmp_path / "evil.csv").exists()
    assert len(list((tmp_path / "uploads").glob("*_evil.csv"))) == 1


def test_data_profile_returns_export_links_and_keeps_session(client, tmp_path: Path):
    csv_path = tmp_path / "sales.csv"
    csv_path.write_text(
        '城市,销售额\n北京,"1,200"\n上海,"1,300"\n', encoding="utf-8"
    )

    with open(csv_path, "rb") as fh:
        resp = client.post(
            "/api/data-profile",
            data={"files": (fh, "sales.csv")},
            content_type="multipart/form-data",
        )

    assert resp.status_code == 200
    body = resp.get_json()
    profile = body["profile"]
    session_id = profile["session_id"]
    assert session_id.startswith("ds_")
    assert profile["exports"]
    assert profile["exports"][0]["csv_url"].startswith("/api/data-profile/export?")

    assert profile["raw_tables"]
    raw = profile["raw_tables"][0]
    assert raw["columns"] == ["城市", "销售额"]
    assert raw["rows"] == 2
    assert raw["csv_url"].startswith("/api/data-profile/export?")
    raw_export = client.get(raw["csv_url"])
    assert raw_export.status_code == 200
    raw_text = raw_export.data.decode("utf-8-sig")
    assert "城市,销售额" in raw_text
    assert "北京,1200" in raw_text

    export = client.get(profile["exports"][0]["csv_url"])
    assert export.status_code == 200
    assert "北京,1200" in export.data.decode("utf-8-sig")
    # 预览结束后会话目录保留，供前端导出
    assert (tmp_path / "datasets" / session_id).is_dir()


def _post_csv(client, tmp_path: Path, name: str, text: str) -> dict:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    with open(path, "rb") as fh:
        resp = client.post(
            "/api/data-profile",
            data={"files": (fh, name)},
            content_type="multipart/form-data",
        )
    assert resp.status_code == 200, resp.data
    return resp.get_json()["profile"]


def test_export_all_raw_tables_as_zip(client, tmp_path: Path):
    profile = _post_csv(
        client, tmp_path, "sales.csv", '城市,销售额\n北京,"1,200"\n上海,"1,300"\n'
    )

    resp = client.get(
        "/api/data-profile/export",
        query_string={"session_id": profile["session_id"], "raw": "all"},
    )

    assert resp.status_code == 200
    assert resp.mimetype == "application/zip"
    with zipfile.ZipFile(io.BytesIO(resp.data)) as archive:
        assert "sales.csv" in archive.namelist()
        text = archive.read("sales.csv").decode("utf-8-sig")
    assert "城市,销售额" in text
    assert "北京,1200" in text


def test_raw_export_rejects_bad_index(client, tmp_path: Path):
    profile = _post_csv(client, tmp_path, "sales.csv", "城市,销售额\n北京,1200\n")
    session_id = profile["session_id"]

    assert (
        client.get(
            "/api/data-profile/export",
            query_string={"session_id": session_id, "raw": "abc"},
        ).status_code
        == 400
    )
    assert (
        client.get(
            "/api/data-profile/export",
            query_string={"session_id": session_id, "raw": "99"},
        ).status_code
        == 404
    )
    assert (
        client.get(
            "/api/data-profile/export",
            query_string={
                "session_id": session_id,
                "raw": "0",
                "series_id": profile["exports"][0]["series_id"],
            },
        ).status_code
        == 400
    )


def test_multiple_files_export_second_raw_table(client, tmp_path: Path):
    first = tmp_path / "a.csv"
    second = tmp_path / "b.csv"
    first.write_text("城市,销售额\n北京,100\n", encoding="utf-8")
    second.write_text("城市,销售额\n上海,200\n", encoding="utf-8")

    with open(first, "rb") as fh1, open(second, "rb") as fh2:
        resp = client.post(
            "/api/data-profile",
            data={"files": [(fh1, "a.csv"), (fh2, "b.csv")]},
            content_type="multipart/form-data",
        )

    assert resp.status_code == 200
    profile = resp.get_json()["profile"]
    assert [table["name"] for table in profile["raw_tables"]] == ["a", "b"]

    export = client.get(profile["raw_tables"][1]["csv_url"])
    assert export.status_code == 200
    text = export.data.decode("utf-8-sig")
    assert "上海,200" in text
