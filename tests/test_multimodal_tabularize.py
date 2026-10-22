"""多模态表格化测试（无需 LLM / 网络）。

覆盖：
- MultimodalReader：图片 -> DataFrame、fenced JSON、list[block] 内容、列名去重、无表报错
- router._route_file：图片走多模态、多模态失败时的降级判定
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

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

    def test_pdf_pages_are_named_p1_p2(self, tmp_path: Path, monkeypatch):
        """多页 PDF：每页一条 RawTable，命名带 _p1/_p2，来源标 #pageN。"""
        pdf = tmp_path / "doc.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")

        monkeypatch.setattr(
            "service.data_ingestion.readers.multimodal_reader._pdf_page_data_urls",
            lambda path, max_pages: [
                "data:image/png;base64,AAA",
                "data:image/png;base64,BBB",
            ],
        )

        class _SeqLLM:
            def __init__(self):
                self.calls = 0

            def invoke(self, messages):
                self.calls += 1
                return _FakeReply(_payload(["城市"], [{"城市": f"城市{self.calls}"}]))

        tables = MultimodalReader.read(str(pdf), llm=_SeqLLM())

        assert [t.name for t in tables] == ["doc_p1", "doc_p2"]
        assert [t.df["城市"].tolist() for t in tables] == [["城市1"], ["城市2"]]
        assert tables[0].source_path.endswith("#page1")
        assert tables[1].source_path.endswith("#page2")

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


# ---------------------------------------------------------------------------
# 模型输出容错：Markdown / HTML / 包装 JSON
# ---------------------------------------------------------------------------


class TestTablePayload:
    @staticmethod
    def _parse(text: str):
        from service.data_ingestion.readers.table_payload import parse_table_response

        return parse_table_response(text)

    def test_markdown_table_is_parsed(self):
        payloads = self._parse(
            "这是识别结果：\n"
            "| 城市 | 销售额（万元） |\n"
            "| --- | ---: |\n"
            "| 北京 | 1200 |\n"
            "| 上海 | 1100 |\n"
        )
        assert len(payloads) == 1
        assert payloads[0]["columns"] == ["城市", "销售额（万元）"]
        assert payloads[0]["rows"][0] == {"城市": "北京", "销售额（万元）": "1200"}
        assert len(payloads[0]["rows"]) == 2

    def test_markdown_tolerates_escaped_pipe_and_emphasis(self):
        payloads = self._parse(
            "| **名称** | `规格` | 数量 |\n"
            "| :--- | :---: | --- |\n"
            "| A \\| B | 10x20 | 3 |\n"
        )
        assert payloads[0]["columns"] == ["名称", "规格", "数量"]
        assert payloads[0]["rows"][0]["名称"] == "A | B"

    def test_multiple_markdown_tables(self):
        payloads = self._parse(
            "| 城市 | 销量 |\n| --- | --- |\n| 北京 | 1 |\n\n"
            "| 产品 | 库存 |\n| --- | --- |\n| A | 30 |\n"
        )
        assert [p["columns"] for p in payloads] == [["城市", "销量"], ["产品", "库存"]]

    def test_markdown_duplicate_headers_are_suffixed(self):
        payloads = self._parse("| 值 | 值 |\n| --- | --- |\n| 1 | 2 |\n")
        assert payloads[0]["columns"] == ["值", "值_2"]
        assert payloads[0]["rows"][0] == {"值": "1", "值_2": "2"}

    def test_html_table_with_merged_cells(self):
        payloads = self._parse(
            "<table>"
            "<tr><th>城市</th><th>季度</th><th>销售额</th></tr>"
            "<tr><td rowspan='2'>北京</td><td>Q1</td><td>100</td></tr>"
            "<tr><td>Q2</td><td>120</td></tr>"
            "</table>"
        )
        assert payloads[0]["columns"] == ["城市", "季度", "销售额"]
        assert [row["城市"] for row in payloads[0]["rows"]] == ["北京", "北京"]
        assert [row["销售额"] for row in payloads[0]["rows"]] == ["100", "120"]

    def test_html_multilevel_header_is_joined_with_underscore(self):
        payloads = self._parse(
            "<table>"
            "<tr><th colspan='2'>2023 年</th><th>备注</th></tr>"
            "<tr><th>Q1</th><th>Q2</th><th></th></tr>"
            "<tr><td>100</td><td>120</td><td>已审</td></tr>"
            "</table>"
        )
        assert payloads[0]["columns"] == ["2023 年_Q1", "2023 年_Q2", "备注"]
        assert payloads[0]["rows"][0]["2023 年_Q1"] == "100"

    def test_json_wrapped_in_data_key(self):
        payloads = self._parse(
            '{"data": {"columns": ["城市"], "rows": [{"城市": "北京"}]}}'
        )
        assert payloads[0]["columns"] == ["城市"]

    def test_rows_as_lists_are_supported(self):
        payloads = self._parse('{"columns": ["城市", "销量"], "rows": [["北京", 12]]}')
        assert payloads[0]["rows"][0] == {"城市": "北京", "销量": 12}

    def test_explicit_empty_table_is_detected(self):
        from service.data_ingestion.readers.table_payload import is_explicit_empty_table

        assert is_explicit_empty_table('{"columns": [], "rows": []}') is True
        assert is_explicit_empty_table('{"tables": []}') is True
        assert is_explicit_empty_table('{"tables": [{"columns": ["a"], "rows": [{"a": 1}]}]}') is False
        assert is_explicit_empty_table("抱歉，我无法识别") is False

    def test_garbage_returns_no_payload(self):
        assert self._parse("抱歉，这张图里没有表格。") == []

    def test_markdown_response_flows_through_reader(self, png: Path):
        """端到端：模型返回 Markdown 表格时，不再直接判定为"没有表"。"""
        llm = _FakeLLM(
            "| 城市 | 销量 |\n| --- | --- |\n| 北京 | 12 |\n| 上海 | 9 |\n"
        )
        tables = MultimodalReader.read(str(png), llm=llm)
        assert tables[0].df["城市"].tolist() == ["北京", "上海"]
        assert tables[0].df["销量"].tolist() == ["12", "9"]


# ---------------------------------------------------------------------------
# 视觉模型选择：请求级 model_type 必须生效
# ---------------------------------------------------------------------------


class TestVisionModelSelection:
    @pytest.fixture(autouse=True)
    def _isolated_env(self, monkeypatch):
        import dotenv

        # 根 .env 有 MODEL_NAME，会让"缺省值"用例不稳定；这里不读 .env
        monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: None)
        monkeypatch.setenv("VISION_BASE_URL", "https://gw.example/v1")
        monkeypatch.setenv("VISION_API_KEY", "test-key")
        for name in ("VISION_MODEL_NAME", "MODEL_NAME"):
            monkeypatch.delenv(name, raising=False)

    @staticmethod
    def _capture(monkeypatch) -> dict:
        import langchain_openai

        captured: dict = {}

        class _Recorder:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        monkeypatch.setattr(langchain_openai, "ChatOpenAI", _Recorder)
        return captured

    def test_request_model_wins_over_env_model_name(self, monkeypatch):
        from service.data_ingestion.readers.multimodal_reader import _load_env_llm

        monkeypatch.setenv("MODEL_NAME", "glm-4.5")
        captured = self._capture(monkeypatch)

        _load_env_llm({"model": "deepseek-v4.1-flash"})

        assert captured["model"] == "deepseek-v4.1-flash"

    def test_vision_model_name_env_wins(self, monkeypatch):
        from service.data_ingestion.readers.multimodal_reader import _load_env_llm

        monkeypatch.setenv("VISION_MODEL_NAME", "qwen-vl-max")
        captured = self._capture(monkeypatch)

        _load_env_llm({"model": "deepseek-v4.1-flash"})

        assert captured["model"] == "qwen-vl-max"

    def test_model_name_env_is_fallback(self, monkeypatch):
        from service.data_ingestion.readers.multimodal_reader import _load_env_llm

        monkeypatch.setenv("MODEL_NAME", "glm-4.7")
        captured = self._capture(monkeypatch)

        _load_env_llm({})

        assert captured["model"] == "glm-4.7"

    def test_default_model_when_nothing_configured(self, monkeypatch):
        from service.data_ingestion.readers.multimodal_reader import _load_env_llm

        captured = self._capture(monkeypatch)

        _load_env_llm(None)

        assert captured["model"] == "glm-4.5v"

    @pytest.mark.asyncio
    async def test_ingest_data_source_forwards_model_type(self, monkeypatch, tmp_path: Path):
        """生成链路：前端启用的模型名要进入 vision_cfg，而不是只剩 url/key。"""
        import service.pipeline.data_source as ds

        captured: dict = {}

        async def fake_ingest(source):
            captured["vision"] = source.options.get("vision")
            return SimpleNamespace(
                series_catalog=None, table_name="x", row_count=1, schema=[]
            )

        monkeypatch.setattr(ds, "ingest", fake_ingest)

        class _Model:
            file_paths = [str(tmp_path / "x.png")]
            user_prompt = "看这个表"
            model_url = "https://gw.example/v1"
            model_api_key = "k"
            model_type = "deepseek-v4.1-flash"
            multi_table = False

        await ds.ingest_data_source(_Model(), "x", [])

        assert captured["vision"] == {
            "base_url": "https://gw.example/v1",
            "api_key": "k",
            "model": "deepseek-v4.1-flash",
        }


# ---------------------------------------------------------------------------
# 解析失败修复重试
# ---------------------------------------------------------------------------


class _SequencedLLM:
    """按顺序返回多条内容的假模型（模拟第一次输出不可解析）。"""

    def __init__(self, contents):
        self.contents = list(contents)
        self.calls = 0
        self.messages: list = []

    def invoke(self, messages):
        self.messages.append(messages)
        index = min(self.calls, len(self.contents) - 1)
        self.calls += 1
        return _FakeReply(self.contents[index])


class TestRepairRetry:
    def test_unparsable_then_valid_json_is_retried(self, png: Path):
        llm = _SequencedLLM(
            ["抱歉，我没能整理成表格。", _payload(["城市"], [{"城市": "北京"}])]
        )

        tables = MultimodalReader.read(str(png), llm=llm)

        assert llm.calls == 2
        assert tables[0].df["城市"].tolist() == ["北京"]
        repair_text = llm.messages[1][-1].content
        assert "只输出 JSON" in repair_text

    def test_explicit_empty_table_is_not_retried(self, png: Path):
        llm = _SequencedLLM(['{"columns": [], "rows": []}'])

        with pytest.raises(ValueError, match="未从图片中提取到结构化表格"):
            MultimodalReader.read(str(png), llm=llm)

        assert llm.calls == 1

    def test_retry_can_be_disabled_by_env(self, png: Path, monkeypatch):
        monkeypatch.setenv("VISION_REPAIR_RETRY", "0")
        llm = _SequencedLLM(
            ["抱歉，我没能整理成表格。", _payload(["城市"], [{"城市": "北京"}])]
        )

        with pytest.raises(ValueError, match="未从图片中提取到结构化表格"):
            MultimodalReader.read(str(png), llm=llm)
        assert llm.calls == 1

    def test_repair_failure_keeps_original_error(self, png: Path):
        llm = _SequencedLLM(["抱歉，我没能整理成表格。", "还是不行"])

        with pytest.raises(ValueError, match="未从图片中提取到结构化表格"):
            MultimodalReader.read(str(png), llm=llm)
        assert llm.calls == 2
