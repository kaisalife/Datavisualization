"""文本表格化结果缓存回归（不调用真实模型）。"""
from __future__ import annotations

from pathlib import Path


class _CountingLLM:
    def __init__(self, payload: str):
        self.payload = payload
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        return {"content": self.payload}


_PAYLOAD = '{"columns":["指标","数值"],"rows":[{"指标":"销量","数值":10}]}'


def _markdown(path: Path, title: str = "销售") -> Path:
    path.write_text(
        f"# {title}\n\n| 指标 | 数值 |\n| 销量 | 10 |\n", encoding="utf-8"
    )
    return path


def _reader(monkeypatch, fake):
    import service.data_ingestion.readers.llm_tabular_reader as ltr

    monkeypatch.setattr(ltr, "_load_env_llm", lambda: fake)
    return ltr.LlmTabularReader


def test_text_cache_reuses_result_for_real_client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LLM_TEXT_CACHE_DIR", str(tmp_path / "cache"))
    fake = _CountingLLM(_PAYLOAD)
    reader = _reader(monkeypatch, fake)
    source = _markdown(tmp_path / "report.md")

    first = reader.read(str(source), table_name="sales")
    second = reader.read(str(source), table_name="sales")

    assert fake.calls == 1
    assert second[0].df.equals(first[0].df)
    assert second[0].name == "sales"
    assert second[0].source_path == str(source)

    # 内容相同但文件名不同（预览 / 图表各自上传的副本）也能命中
    copied = _markdown(tmp_path / "another.md")
    third = reader.read(str(copied), table_name="sales")
    assert fake.calls == 1
    assert third[0].source_path == str(copied)

    # 内容变了必须重新调用
    changed = _markdown(tmp_path / "changed.md", title="库存")
    reader.read(str(changed), table_name="sales")
    assert fake.calls == 2


def test_text_cache_keys_on_max_text_chars(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LLM_TEXT_CACHE_DIR", str(tmp_path / "cache"))
    fake = _CountingLLM(_PAYLOAD)
    reader = _reader(monkeypatch, fake)
    source = _markdown(tmp_path / "report.md")

    reader.read(str(source), table_name="sales", max_text_chars=100)
    reader.read(str(source), table_name="sales", max_text_chars=50)

    assert fake.calls == 2


def test_text_cache_skips_injected_llm(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LLM_TEXT_CACHE_DIR", str(tmp_path / "cache"))
    fake = _CountingLLM(_PAYLOAD)
    reader = _reader(monkeypatch, fake)
    source = _markdown(tmp_path / "report.md")

    reader.read(str(source), llm=fake, table_name="sales")
    reader.read(str(source), llm=fake, table_name="sales")

    assert fake.calls == 2


def test_text_cache_respects_global_switch(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LLM_TEXT_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("VISION_CACHE", "0")
    fake = _CountingLLM(_PAYLOAD)
    reader = _reader(monkeypatch, fake)
    source = _markdown(tmp_path / "report.md")

    reader.read(str(source), table_name="sales")
    reader.read(str(source), table_name="sales")

    assert fake.calls == 2
