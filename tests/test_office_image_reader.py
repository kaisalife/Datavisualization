"""OOXML 内嵌图片 -> 表格 测试（离线，假视觉模型）。

覆盖：图片过滤/排序、单图与多图命名、抽表失败分支、router 兜底与不误降级。
"""
from __future__ import annotations

import io
import json
import os
import zipfile
from pathlib import Path

import pandas as pd
import pytest
from PIL import Image

from service.data_ingestion import router
from service.data_ingestion.models import DataSource, RawTable
from service.data_ingestion.readers.office_image_reader import (
    NoEmbeddedImages,
    OfficeImageReader,
)

pytestmark = pytest.mark.whitebox


def _png(size: tuple[int, int] = (400, 300), noise: bool = True) -> bytes:
    """生成 PNG；noise=True 保证体积超过默认 4KB 阈值。"""
    if noise:
        img = Image.frombytes("RGB", size, os.urandom(size[0] * size[1] * 3))
    else:
        img = Image.new("RGB", size, "white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_ooxml(path: Path, images: dict[str, bytes], media_dir: str = "word/media") -> Path:
    """造一个最小 OOXML 包（docx/pptx/xlsx 的媒体目录可指定）。"""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", "<w:document/>")
        for name, payload in images.items():
            zf.writestr(f"{media_dir}/{name}", payload)
    return path


class FakeVisionLLM:
    """返回固定 JSON 的假视觉模型。"""

    def __init__(self, payload: dict | None = None, raw: str | None = None):
        self.payload = payload if payload is not None else {
            "columns": ["城市", "2024 年"],
            "rows": [{"城市": "北京", "2024 年": 1500}],
        }
        self.raw = raw
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        content = self.raw if self.raw is not None else json.dumps(self.payload, ensure_ascii=False)
        return {"content": content}


def _degenerate_tables() -> list[RawTable]:
    """模拟 Unstructured 只抽到正文（单列 content）。"""
    return [
        RawTable(
            name="doc",
            df=pd.DataFrame({"content": ["这是一段正文"]}),
            source_kind="document",
            source_path="doc.docx",
        )
    ]


# ---------------------------------------------------------------- extract_images


def test_extract_images_filters_icons_and_keeps_natural_order(tmp_path):
    docx = _make_ooxml(
        tmp_path / "a.docx",
        {
            "image10.png": _png(),
            "image2.png": _png(),
            "icon.png": _png((32, 32), noise=False),
        },
    )

    images = OfficeImageReader.extract_images(docx)

    assert [name.split("/")[-1] for name, _ in images] == ["image2.png", "image10.png"]


def test_extract_images_raises_when_only_icons(tmp_path):
    docx = _make_ooxml(tmp_path / "icons.docx", {"icon.png": _png((32, 32), noise=False)})

    with pytest.raises(NoEmbeddedImages):
        OfficeImageReader.extract_images(docx)


def test_extract_images_raises_for_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        OfficeImageReader.extract_images(tmp_path / "missing.docx")


def test_extract_images_caps_count(tmp_path):
    docx = _make_ooxml(
        tmp_path / "many.pptx",
        {f"image{i}.png": _png() for i in range(1, 6)},
        media_dir="ppt/media",
    )

    images = OfficeImageReader.extract_images(docx, max_images=3)

    assert [name.split("/")[-1] for name, _ in images] == ["image1.png", "image2.png", "image3.png"]


# ---------------------------------------------------------------- read


def test_read_converts_single_image_to_table(tmp_path):
    docx = _make_ooxml(tmp_path / "sales.docx", {"image1.png": _png()})
    llm = FakeVisionLLM()

    tables = OfficeImageReader.read(docx, table_name="销售", llm=llm)

    assert llm.calls == 1
    assert len(tables) == 1
    assert tables[0].name == "销售"
    assert list(tables[0].df.columns) == ["城市", "2024 年"]
    assert tables[0].df.iloc[0].tolist() == ["北京", 1500]
    assert "word/media/image1.png" in tables[0].source_path


def test_read_names_multiple_images_with_suffix(tmp_path):
    docx = _make_ooxml(tmp_path / "deck.pptx", {"image1.png": _png(), "image2.png": _png()}, media_dir="ppt/media")

    tables = OfficeImageReader.read(docx, table_name="deck", llm=FakeVisionLLM())

    assert [t.name for t in tables] == ["deck_img1", "deck_img2"]


def test_read_raises_when_model_returns_unparsable_content(tmp_path):
    docx = _make_ooxml(tmp_path / "bad.docx", {"image1.png": _png()})

    with pytest.raises(ValueError, match="均未提取到表格"):
        OfficeImageReader.read(docx, llm=FakeVisionLLM(raw="抱歉，我看不清这张图"))


def test_read_raises_when_no_images(tmp_path):
    docx = _make_ooxml(tmp_path / "textonly.docx", {})

    with pytest.raises(NoEmbeddedImages):
        OfficeImageReader.read(docx, llm=FakeVisionLLM())


# ---------------------------------------------------------------- router 兜底


def test_router_falls_back_to_embedded_images(monkeypatch, tmp_path):
    docx = _make_ooxml(tmp_path / "report.docx", {"image1.png": _png()})
    vision_table = pd.DataFrame({"城市": ["北京"], "2024 年": [1500]})

    monkeypatch.setattr(
        router.DocumentReader, "read", staticmethod(lambda *a, **k: _degenerate_tables())
    )
    monkeypatch.setattr(
        router.OfficeImageReader,
        "read",
        staticmethod(
            lambda *a, **k: [
                RawTable(name="report", df=vision_table, source_kind="document", source_path="s")
            ]
        ),
    )

    out = router._route_file(DataSource(kind="file", path=str(docx)))

    assert out[0].df.equals(vision_table)


def test_router_keeps_text_when_doc_has_no_images(monkeypatch, tmp_path):
    docx = _make_ooxml(tmp_path / "textonly.docx", {})
    monkeypatch.setattr(
        router.DocumentReader, "read", staticmethod(lambda *a, **k: _degenerate_tables())
    )

    def _no_images(*args, **kwargs):
        raise NoEmbeddedImages("没有图片")

    monkeypatch.setattr(router.OfficeImageReader, "read", staticmethod(_no_images))

    out = router._route_file(DataSource(kind="file", path=str(docx)))

    assert out[0].df.columns.tolist() == ["content"]
    assert out[0].degraded is False


def test_router_marks_degraded_when_vision_fails(monkeypatch, tmp_path):
    docx = _make_ooxml(tmp_path / "report.docx", {"image1.png": _png()})
    monkeypatch.setattr(
        router.DocumentReader, "read", staticmethod(lambda *a, **k: _degenerate_tables())
    )
    monkeypatch.setattr(
        router.OfficeImageReader,
        "read",
        staticmethod(lambda *a, **k: (_ for _ in ()).throw(RuntimeError("vision down"))),
    )

    out = router._route_file(DataSource(kind="file", path=str(docx)))

    assert out[0].degraded is True
    assert "multimodal_failed" in out[0].degraded_reason


def test_router_skips_vision_when_text_layer_has_table(monkeypatch, tmp_path):
    docx = _make_ooxml(tmp_path / "ok.docx", {"image1.png": _png()})
    real_table = pd.DataFrame({"城市": ["北京"], "销量": [10]})
    monkeypatch.setattr(
        router.DocumentReader,
        "read",
        staticmethod(
            lambda *a, **k: [
                RawTable(name="ok", df=real_table, source_kind="document", source_path="s")
            ]
        ),
    )
    monkeypatch.setattr(
        router.OfficeImageReader,
        "read",
        staticmethod(lambda *a, **k: (_ for _ in ()).throw(AssertionError("不应调用视觉兜底"))),
    )

    out = router._route_file(DataSource(kind="file", path=str(docx)))

    assert out[0].df.equals(real_table)


def test_router_xlsx_chart_only_falls_back(monkeypatch, tmp_path):
    xlsx = _make_ooxml(
        tmp_path / "chart_only.xlsx", {"image1.png": _png()}, media_dir="xl/media"
    )
    vision_table = pd.DataFrame({"季度": ["Q1"], "销量": [42]})
    monkeypatch.setattr(
        router.ExcelReader,
        "read",
        staticmethod(lambda *a, **k: (_ for _ in ()).throw(ValueError("no sheets"))),
    )
    monkeypatch.setattr(
        router.OfficeImageReader,
        "read",
        staticmethod(
            lambda *a, **k: [
                RawTable(name="chart_only", df=vision_table, source_kind="document", source_path="s")
            ]
        ),
    )

    out = router._route_file(DataSource(kind="file", path=str(xlsx)))

    assert out[0].df.equals(vision_table)
