"""多模态抽表缓存回归（不调用真实视觉模型）。"""
from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path

import pandas as pd
import pytest
from PIL import Image

from service.data_ingestion.models import RawTable
from service.data_ingestion.vision_cache import (
    cache_enabled,
    cache_key,
    load_tables,
    save_tables,
)


def test_cache_enabled_env(monkeypatch):
    monkeypatch.delenv("VISION_CACHE", raising=False)
    assert cache_enabled()

    for value in ("0", "false", "off", "no", " OFF "):
        monkeypatch.setenv("VISION_CACHE", value)
        assert not cache_enabled()

    monkeypatch.setenv("VISION_CACHE", "1")
    assert cache_enabled()


def test_cache_key_depends_on_content_and_options(tmp_path: Path):
    source = tmp_path / "a.png"
    source.write_bytes(b"abc")
    other = tmp_path / "b.png"
    other.write_bytes(b"xyz")

    base = cache_key(source, base_name="sales", hint="画柱状图", multi_table=False)
    assert base == cache_key(source, base_name="sales", hint=" 画柱状图 ", multi_table=False)
    assert base != cache_key(source, base_name="sales", hint="画饼图", multi_table=False)
    assert base != cache_key(source, base_name="other", hint="画柱状图", multi_table=False)
    assert base != cache_key(source, base_name="sales", hint="画柱状图", multi_table=True)
    assert base != cache_key(other, base_name="sales", hint="画柱状图", multi_table=False)
    assert base != cache_key(source, base_name="sales", hint="画柱状图", multi_table=False, max_tables=1)
    assert base != cache_key(source, base_name="sales", hint="画柱状图", multi_table=False, max_side=1000)


def _tables(source: Path) -> list[RawTable]:
    return [
        RawTable(
            name="sales",
            df=pd.DataFrame({"城市": ["北京", "上海"], "销售额": [1200, 1500]}),
            source_kind="document",
            source_path=f"{source}#page1",
        )
    ]


def test_save_and_load_roundtrip_rewrites_source_path(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("VISION_CACHE_DIR", str(tmp_path / "cache"))
    source = tmp_path / "a.png"
    source.write_bytes(b"abc")
    tables = _tables(source)
    key = cache_key(source, base_name="sales", hint="画图")

    assert save_tables(key, tables, source)

    loaded = load_tables(key, source)
    assert loaded is not None
    assert loaded[0].name == "sales"
    assert loaded[0].df.to_dict("records") == [
        {"城市": "北京", "销售额": 1200},
        {"城市": "上海", "销售额": 1500},
    ]
    assert loaded[0].source_path == f"{source}#page1"

    # 同一内容上传到另一个路径（预览/图表各存一份）：source_path 跟着当前路径走
    copied = tmp_path / "b.png"
    copied.write_bytes(b"abc")
    loaded_copy = load_tables(key, copied)
    assert loaded_copy is not None
    assert loaded_copy[0].source_path == f"{copied}#page1"


def test_load_returns_none_for_missing_or_broken_cache(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("VISION_CACHE_DIR", str(tmp_path / "cache"))

    assert load_tables("missing", tmp_path / "a.png") is None

    broken = tmp_path / "cache" / "broken"
    broken.mkdir(parents=True)
    (broken / "meta.json").write_text("{not-json", encoding="utf-8")
    assert load_tables("broken", tmp_path / "a.png") is None


def _png(path: Path) -> Path:
    Image.new("RGB", (64, 64), (255, 255, 255)).save(path)
    return path


class _CountingLLM:
    def __init__(self, payload: str):
        self.payload = payload
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        return {"content": self.payload}


def test_multimodal_read_reuses_cache_for_real_client(tmp_path: Path, monkeypatch):
    import service.data_ingestion.readers.multimodal_reader as mr

    monkeypatch.setenv("VISION_CACHE_DIR", str(tmp_path / "cache"))
    payload = (
        '{"columns":["城市","销售额"],"rows":['
        '{"城市":"北京","销售额":1200},{"城市":"上海","销售额":1500}]}'
    )
    fake = _CountingLLM(payload)
    monkeypatch.setattr(mr, "_load_env_llm", lambda cfg=None: fake)
    image = _png(tmp_path / "chart.png")

    first = mr.MultimodalReader.read(str(image), table_name="sales", hint="画柱状图")
    second = mr.MultimodalReader.read(str(image), table_name="sales", hint="画柱状图")

    assert fake.calls == 1
    assert second[0].df.to_dict("records") == first[0].df.to_dict("records")

    # hint 改变会重新调用视觉模型
    mr.MultimodalReader.read(str(image), table_name="sales", hint="画饼图")
    assert fake.calls == 2


def test_multimodal_read_skips_cache_for_injected_llm(tmp_path: Path, monkeypatch):
    import service.data_ingestion.readers.multimodal_reader as mr

    monkeypatch.setenv("VISION_CACHE_DIR", str(tmp_path / "cache"))
    payload = '{"columns":["城市","销售额"],"rows":[{"城市":"北京","销售额":1200}]}'
    injected = _CountingLLM(payload)
    image = _png(tmp_path / "chart.png")

    mr.MultimodalReader.read(str(image), llm=injected, table_name="sales", hint="画图")
    mr.MultimodalReader.read(str(image), llm=injected, table_name="sales", hint="画图")

    assert injected.calls == 2


def _noisy_png(size: tuple[int, int] = (400, 300)) -> bytes:
    """随机噪声保证超过内嵌图片默认 4KB 阈值。"""
    img = Image.frombytes("RGB", size, os.urandom(size[0] * size[1] * 3))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _docx_with_image(path: Path) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", "<w:document/>")
        zf.writestr("word/media/image1.png", _noisy_png())
    return path


def test_office_read_reuses_cache_for_real_client(tmp_path: Path, monkeypatch):
    import service.data_ingestion.readers.office_image_reader as oir

    monkeypatch.setenv("VISION_CACHE_DIR", str(tmp_path / "cache"))
    payload = '{"columns":["城市","销售额"],"rows":[{"城市":"北京","销售额":1200}]}'
    fake = _CountingLLM(payload)
    monkeypatch.setattr(oir, "load_vision_llm", lambda cfg=None: fake)
    docx = _docx_with_image(tmp_path / "report.docx")

    first = oir.OfficeImageReader.read(str(docx), table_name="sales", hint="画柱状图")
    second = oir.OfficeImageReader.read(str(docx), table_name="sales", hint="画柱状图")

    assert fake.calls == 1
    assert second[0].df.equals(first[0].df)
    assert second[0].source_path.startswith(str(docx))
