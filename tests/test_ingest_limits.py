"""数据接入内存护栏（CSV/TSV/Excel）：超限显式拒绝，不静默截断。"""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import pytest

from service.data_ingestion.limits import DataTooLargeError, ingest_limits
from service.data_ingestion.readers.excel_reader import ExcelReader
from service.data_ingestion.readers.file_reader import FileReader

pytestmark = pytest.mark.whitebox


def _write_csv(path: Path, rows: int, cols: int = 3) -> Path:
    header = ",".join(f"c{index}" for index in range(cols))
    body = "\n".join(
        ",".join(str(row * 10 + col) for col in range(cols)) for row in range(rows)
    )
    path.write_text(f"{header}\n{body}\n", encoding="utf-8")
    return path


class TestCsvLimits:
    def test_rows_over_limit_are_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MAX_INGEST_ROWS", "10")
        monkeypatch.setenv("MAX_INGEST_CELLS", "0")
        path = _write_csv(tmp_path / "big.csv", rows=50)

        with pytest.raises(DataTooLargeError, match="接入上限"):
            FileReader.read(str(path))

    def test_cell_limit_is_enforced(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MAX_INGEST_ROWS", "0")
        monkeypatch.setenv("MAX_INGEST_CELLS", "12")
        path = _write_csv(tmp_path / "wide.csv", rows=10, cols=5)

        with pytest.raises(DataTooLargeError, match="单元格"):
            FileReader.read(str(path))

    def test_small_file_passes(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MAX_INGEST_ROWS", "100")
        monkeypatch.setenv("MAX_INGEST_CELLS", "1000")
        path = _write_csv(tmp_path / "small.csv", rows=10)

        tables = FileReader.read(str(path))

        assert len(tables[0].df) == 10

    def test_zero_disables_limits(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MAX_INGEST_ROWS", "0")
        monkeypatch.setenv("MAX_INGEST_CELLS", "0")
        path = _write_csv(tmp_path / "unlimited.csv", rows=200)

        assert len(FileReader.read(str(path))[0].df) == 200
        assert ingest_limits() == (0, 0)


class TestExcelLimits:
    def test_dimensions_are_checked_before_full_pandas_read(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MAX_INGEST_ROWS", "5")
        monkeypatch.setenv("MAX_INGEST_CELLS", "0")
        path = tmp_path / "big.xlsx"
        pd.DataFrame({"a": range(30), "b": range(30)}).to_excel(path, index=False)

        calls = []
        real_read_excel = pd.read_excel

        def _spy(*args, **kwargs):
            calls.append(dict(kwargs))
            if "nrows" not in kwargs:
                raise AssertionError("超限 Excel 不应进入全量 pandas 读取")
            return real_read_excel(*args, **kwargs)

        monkeypatch.setattr(pd, "read_excel", _spy)

        with pytest.raises(DataTooLargeError, match="接入上限"):
            ExcelReader.read(str(path))

        assert calls, "应先做有界探测"
        assert all("nrows" in kwargs for kwargs in calls)

    def test_cell_limit_applies_to_wide_excel(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MAX_INGEST_ROWS", "0")
        monkeypatch.setenv("MAX_INGEST_CELLS", "50")
        path = tmp_path / "wide.xlsx"
        pd.DataFrame({f"c{i}": [1, 2] for i in range(60)}).to_excel(path, index=False)

        with pytest.raises(DataTooLargeError, match="单元格"):
            ExcelReader.read(str(path))

    def test_small_excel_passes(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MAX_INGEST_ROWS", "100")
        monkeypatch.setenv("MAX_INGEST_CELLS", "1000")
        path = tmp_path / "small.xlsx"
        pd.DataFrame({"城市": ["北京", "上海"], "销量": [12, 9]}).to_excel(path, index=False)

        tables = ExcelReader.read(str(path))

        assert len(tables) == 1
        assert len(tables[0].df) == 2

    def test_router_does_not_fall_back_to_embedded_images(self, tmp_path, monkeypatch):
        """超限是数据规模问题，不能当成"纯图表工作簿"去抽内嵌图片。"""
        from service.data_ingestion import router
        from service.data_ingestion.models import DataSource

        path = tmp_path / "big.xlsx"
        path.write_bytes(b"not-a-real-xlsx")
        monkeypatch.setattr(router.ExcelReader, "can_handle", staticmethod(lambda _p: True))

        def _too_large(*_args, **_kwargs):
            raise DataTooLargeError("too big")

        monkeypatch.setattr(router.ExcelReader, "read", staticmethod(_too_large))
        called = []
        monkeypatch.setattr(router.OfficeImageReader, "can_handle", staticmethod(lambda _p: True))
        monkeypatch.setattr(
            router.OfficeImageReader, "read", staticmethod(lambda *a, **k: called.append(1) or [])
        )

        with pytest.raises(DataTooLargeError):
            router._route_file(DataSource(kind="file", path=str(path)))

        assert called == []


class TestDataProfileApi:
    def test_oversized_csv_returns_400_with_reason(self, tmp_path, monkeypatch):
        import app as app_module

        monkeypatch.setenv("MAX_INGEST_ROWS", "5")
        monkeypatch.setenv("MAX_INGEST_CELLS", "0")
        monkeypatch.setenv("SERVICE_API_KEY", "")
        app_module.app.config["_SERVICE_API_KEY"] = ""
        uploads = tmp_path / "uploads"
        uploads.mkdir()
        app_module.app.config["_UPLOAD_DIR"] = uploads
        client = app_module.app.test_client()

        csv_content = "城市,销量\n" + "\n".join(f"城市{i},{i}" for i in range(20))
        resp = client.post(
            "/api/data-profile",
            data={"files": (io.BytesIO(csv_content.encode("utf-8")), "big.csv")},
            content_type="multipart/form-data",
        )

        assert resp.status_code == 400, resp.get_json()
        detail = resp.get_json()["detail"]
        assert "接入上限" in detail
        assert "MAX_INGEST_ROWS" in detail
