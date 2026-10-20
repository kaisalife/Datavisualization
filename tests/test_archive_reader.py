"""压缩包安全解压与递归读取回归（不联网）。"""
from __future__ import annotations

import gzip
import io
import tarfile
import zipfile

import pytest

from service.data_ingestion.readers.archive_reader import ArchiveReader


def _csv_bytes() -> bytes:
    return "城市,销售额\n北京,1200\n上海,1500\n".encode("utf-8")


def _make_zip(path, files: dict[str, bytes]):
    with zipfile.ZipFile(path, "w") as zf:
        for name, payload in files.items():
            zf.writestr(name, payload)


def test_read_normal_zip(tmp_path):
    zip_path = tmp_path / "bundle.zip"
    _make_zip(zip_path, {"sales.csv": _csv_bytes()})

    tables = ArchiveReader.read(str(zip_path))

    assert len(tables) == 1
    assert tables[0].df.to_dict("records") == [
        {"城市": "北京", "销售额": 1200},
        {"城市": "上海", "销售额": 1500},
    ]


def test_read_nested_zip(tmp_path):
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as zf:
        zf.writestr("sales.csv", _csv_bytes())

    zip_path = tmp_path / "outer.zip"
    _make_zip(zip_path, {"inner.zip": inner.getvalue()})

    tables = ArchiveReader.read(str(zip_path))

    assert len(tables) == 1
    assert len(tables[0].df) == 2


def test_zip_slip_is_rejected_without_writing_outside(tmp_path):
    zip_path = tmp_path / "evil.zip"
    _make_zip(zip_path, {"../evil.csv": _csv_bytes(), "sales.csv": _csv_bytes()})

    with pytest.raises(ValueError, match="越界"):
        ArchiveReader.read(str(zip_path))

    assert not (tmp_path / "evil.csv").exists()
    assert not (tmp_path.parent / "evil.csv").exists()


def test_zip_member_count_limit(tmp_path, monkeypatch):
    zip_path = tmp_path / "many.zip"
    _make_zip(zip_path, {"a.csv": _csv_bytes(), "b.csv": _csv_bytes()})
    monkeypatch.setenv("ARCHIVE_MAX_FILES", "1")

    with pytest.raises(ValueError, match="文件数超过上限"):
        ArchiveReader.read(str(zip_path))


def test_zip_uncompressed_size_limit(tmp_path, monkeypatch):
    zip_path = tmp_path / "big.zip"
    _make_zip(zip_path, {"sales.csv": _csv_bytes()})
    monkeypatch.setenv("ARCHIVE_MAX_BYTES", "10")

    with pytest.raises(ValueError, match="大小超过上限"):
        ArchiveReader.read(str(zip_path))


def test_tar_symlink_is_rejected(tmp_path):
    tar_path = tmp_path / "bundle.tar"
    with tarfile.open(tar_path, "w") as tf:
        info = tarfile.TarInfo("sales.csv")
        payload = _csv_bytes()
        info.size = len(payload)
        tf.addfile(info, io.BytesIO(payload))
        link = tarfile.TarInfo("link.csv")
        link.type = tarfile.SYMTYPE
        link.linkname = "sales.csv"
        tf.addfile(link)

    with pytest.raises(ValueError, match="符号链接"):
        ArchiveReader.read(str(tar_path))


def test_read_gzip_single_file(tmp_path):
    gz_path = tmp_path / "sales.csv.gz"
    with gzip.open(gz_path, "wb") as f:
        f.write(_csv_bytes())

    tables = ArchiveReader.read(str(gz_path))

    assert len(tables) == 1
    assert len(tables[0].df) == 2


def test_gzip_size_limit(tmp_path, monkeypatch):
    gz_path = tmp_path / "sales.csv.gz"
    with gzip.open(gz_path, "wb") as f:
        f.write(_csv_bytes())
    monkeypatch.setenv("ARCHIVE_MAX_BYTES", "10")

    with pytest.raises(ValueError, match="大小超过上限"):
        ArchiveReader.read(str(gz_path))
