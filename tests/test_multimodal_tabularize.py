"""多模态表格化测试（无需 LLM / 网络）。

覆盖：
- MultimodalReader：图片 -> DataFrame、fenced JSON、list[block] 内容、列名去重、无表报错
- router._route_file：图片走多模态、多模态失败时的降级判定
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from service.data_ingestion.models import DataSource, RawTable
from service.data_ingestion.readers.multimodal_reader import MultimodalReader
from service.data_ingestion.router import _is_degenerate, _route_file

pytestmark = pytest.mark.whitebox


class _FakeReply:
    def __init__(self, content):
        self.content = content


class _FakeLLM:
    """记录调用参数、返回固定内容的假视觉模型。"""

    def __init__(self, content):
        self.content = content
        self.calls = 0
        self.last_messages = None

    def invoke(self, messages):
        self.calls += 1
        self.last_messages = messages
        return _FakeReply(self.content)


@pytest.fixture
def png(tmp_path: Path) -> Path:
    """一张空白 PNG（内容无关，模型被替换）。"""
    from PIL import Image

    path = tmp_path / "table.png"
    Image.new("RGB", (320, 160), (255, 255, 255)).save(path)
    return path


def _payload(columns, rows) -> str:
    return json.dumps({"columns": columns, "rows": rows}, ensure_ascii=False)


class TestMultimodalReader:
    def test_image_to_dataframe_and_carries_data_url(self, png: Path):
        content = f"```json\n{_payload(['年份', '销售额（万元）'], [{'年份': 2023, '销售额（万元）': 1200}, {'年份': 2024, '销售额（万元）': 1500}])}\n```"
        llm = _FakeLLM(content)

        tables = MultimodalReader.read(str(png), llm=llm)

        assert len(tables) == 1
        df = tables[0].df
        assert list(df.columns) == ["年份", "销售额（万元）"]
        assert df["销售额（万元）"].tolist() == [1200, 1500]
        assert tables[0].source_kind == "document"

        # 图片必须以 data URL 形式进入消息
        blocks = llm.last_messages[-1].content
        assert blocks[1]["image_url"]["url"].startswith("data:image/png;base64,")

    def test_list_block_content_is_supported(self, png: Path):
        llm = _FakeLLM([{"type": "text", "text": _payload(["城市"], [{"城市": "北京"}])}])

        tables = MultimodalReader.read(str(png), llm=llm)

        assert tables[0].df["城市"].tolist() == ["北京"]

    def test_duplicate_and_blank_columns_are_normalized(self, png: Path):
        content = _payload(["值", "值", ""], [{"值": 1, "值_2": 2, "col_3": 3}])

        df = MultimodalReader.read(str(png), llm=_FakeLLM(content))[0].df

        assert list(df.columns) == ["值", "值_2", "col_3"]

    def test_raises_when_no_table(self, png: Path):
        with pytest.raises(ValueError, match="未从图片中提取到结构化表格"):
            MultimodalReader.read(str(png), llm=_FakeLLM('{"columns": [], "rows": []}'))

    def test_reasoning_only_response_gives_actionable_error(self, png: Path):
        """推理模型把 max_tokens 花在 reasoning 上时，报错要指向 VISION_MAX_TOKENS。"""

        class _ReasoningOnlyLLM:
            def invoke(self, messages):
                return {"content": "", "reasoning_content": "让我想想……"}

        # 单页失败会被 read() 汇总成 ValueError，但原始原因要透传给用户
        with pytest.raises(ValueError, match="VISION_MAX_TOKENS"):
            MultimodalReader.read(str(png), llm=_ReasoningOnlyLLM())

    def test_blank_response_without_reasoning_raises(self, png: Path):
        with pytest.raises(ValueError, match="返回空内容"):
            MultimodalReader.read(str(png), llm=_FakeLLM(""))

    def test_missing_file_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            MultimodalReader.read(str(tmp_path / "nope.png"), llm=_FakeLLM("{}"))

    def test_can_handle_covers_images_and_pdf(self):
        assert MultimodalReader.can_handle("a.PNG")
        assert MultimodalReader.can_handle("a.jpeg")
        assert MultimodalReader.can_handle("a.heic")
        assert MultimodalReader.can_handle("a.avif")
        assert MultimodalReader.can_handle("a.pdf")
        assert not MultimodalReader.can_handle("a.csv")

    def test_heic_image_is_decoded_and_converted(self, tmp_path: Path):
        """iPhone 照片（HEIC）经 pillow-heif 解码后以 JPEG data URL 送模型。"""
        pytest.importorskip("pillow_heif")
        from PIL import Image
        from pillow_heif import register_heif_opener

        register_heif_opener()
        path = tmp_path / "photo.heic"
        Image.new("RGB", (320, 160), "white").save(path)

        llm = _FakeLLM(_payload(["城市"], [{"城市": "北京"}]))
        tables = MultimodalReader.read(str(path), llm=llm)

        assert tables[0].df["城市"].tolist() == ["北京"]
        data_url = llm.last_messages[-1].content[1]["image_url"]["url"]
        assert data_url.startswith("data:image/jpeg;base64,")

    def test_avif_image_is_decoded(self, tmp_path: Path):
        from PIL import Image, features

        if not features.check("avif"):
            pytest.skip("当前 Pillow 未编译 AVIF 支持")

        path = tmp_path / "shot.avif"
        Image.new("RGB", (320, 160), "white").save(path, format="AVIF")

        llm = _FakeLLM(_payload(["城市"], [{"城市": "上海"}]))
        tables = MultimodalReader.read(str(path), llm=llm)

        assert tables[0].df["城市"].tolist() == ["上海"]


class TestMultimodalMultiTable:
    """一图多表：VISION_MULTI_TABLE / multi_table=True 时逐张输出。"""

    @staticmethod
    def _two_tables() -> str:
        return json.dumps(
            {
                "tables": [
                    {
                        "title": "区域销售",
                        "columns": ["城市", "2024 年"],
                        "rows": [{"城市": "北京", "2024 年": 1500}],
                    },
                    {
                        "title": "库存",
                        "columns": ["产品", "库存"],
                        "rows": [{"产品": "A", "库存": 30}],
                    },
                ]
            },
            ensure_ascii=False,
        )

    def test_multi_table_payload_returns_all_tables(self, png: Path):
        tables = MultimodalReader.read(
            str(png), llm=_FakeLLM(self._two_tables()), multi_table=True
        )

        assert [t.name for t in tables] == ["table_t1", "table_t2"]
        assert list(tables[0].df.columns) == ["城市", "2024 年"]
        assert list(tables[1].df.columns) == ["产品", "库存"]
        assert tables[0].source_path.endswith("/table1")

    def test_default_mode_keeps_only_first_table(self, png: Path):
        tables = MultimodalReader.read(str(png), llm=_FakeLLM(self._two_tables()))

        assert len(tables) == 1
        assert tables[0].name == "table"
        assert list(tables[0].df.columns) == ["城市", "2024 年"]

    def test_env_flag_enables_multi_table(self, png: Path, monkeypatch):
        monkeypatch.setenv("VISION_MULTI_TABLE", "1")

        tables = MultimodalReader.read(str(png), llm=_FakeLLM(self._two_tables()))

        assert [t.name for t in tables] == ["table_t1", "table_t2"]

    def test_multi_mode_prompt_requests_tables_array(self, png: Path):
        llm = _FakeLLM(self._two_tables())

        MultimodalReader.read(str(png), llm=llm, multi_table=True)

        system_prompt = llm.last_messages[0].content
        assert '"tables"' in system_prompt
        assert "最多输出 5 张表" in system_prompt

    def test_multi_mode_tolerates_single_table_schema(self, png: Path):
        content = _payload(["城市"], [{"城市": "北京"}])

        tables = MultimodalReader.read(str(png), llm=_FakeLLM(content), multi_table=True)

        assert len(tables) == 1
        assert tables[0].name == "table"

    def test_table_count_is_capped(self, png: Path, monkeypatch):
        monkeypatch.setenv("VISION_MAX_TABLES", "2")
        content = json.dumps(
            {
                "tables": [
                    {"columns": ["c"], "rows": [{"c": i}]} for i in range(3)
                ]
            }
        )

        tables = MultimodalReader.read(str(png), llm=_FakeLLM(content), multi_table=True)

        assert len(tables) == 2


class TestRouterMultimodal:
    def test_image_routes_to_multimodal(self, png: Path, monkeypatch):
        calls = {}

        def fake_read(
            path,
            table_name=None,
            llm=None,
            hint="",
            max_pages=None,
            vision_cfg=None,
            multi_table=None,
        ):
            calls["hint"] = hint
            calls["table_name"] = table_name
            calls["multi_table"] = multi_table
            return [RawTable(name="t", df=pd.DataFrame({"a": [1]}), source_kind="document", source_path=path)]

        monkeypatch.setattr(MultimodalReader, "read", staticmethod(fake_read))

        source = DataSource(kind="file", path=str(png), name="mytable", options={"vision_hint": "按年份对比"})
        tables = _route_file(source)

        assert calls["hint"] == "按年份对比"
        assert calls["table_name"] == "mytable"
        assert calls["multi_table"] is None
        assert tables[0].name == "t"

    def test_multi_table_option_is_forwarded(self, png: Path, monkeypatch):
        calls = {}

        def fake_read(path, **kwargs):
            calls.update(kwargs)
            return [RawTable(name="t", df=pd.DataFrame({"a": [1]}), source_kind="document", source_path=path)]

        monkeypatch.setattr(MultimodalReader, "read", staticmethod(fake_read))

        _route_file(
            DataSource(
                kind="file",
                path=str(png),
                options={"vision_multi_table": True},
            )
        )

        assert calls["multi_table"] is True

    def test_build_file_options_multi_table_flag(self):
        from service.data_ingestion.router import build_file_options

        assert "vision_multi_table" not in build_file_options()
        assert build_file_options(multi_table=True)["vision_multi_table"] is True

    def test_degenerate_detection(self):
        degen = [RawTable(name="a", df=pd.DataFrame({"content": ["x"]}), source_kind="document", source_path="p")]
        good = [RawTable(name="a", df=pd.DataFrame({"a": [1], "b": [2]}), source_kind="document", source_path="p")]

        assert _is_degenerate(degen) is True
        assert _is_degenerate(good) is False
        assert _is_degenerate([]) is True
