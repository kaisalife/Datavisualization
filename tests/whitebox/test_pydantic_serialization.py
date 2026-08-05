"""白盒测试：Pydantic 模型序列化。

验证所有 Pydantic BaseModel 的 model_dump() 输出格式正确，
且不触发 Pydantic V2 弃用警告。
"""
import warnings

import pytest
from pydantic import ValidationError

from Entity import (
    CompleteVizCodeRequest,
    ErrorResponse,
    GenerateChartWithPromptRequest,
    GenerateChartWithPromptResponse,
    GetChartRequest,
)


# ============================================================
# ErrorResponse
# ============================================================

class TestErrorResponseSerialization:
    """ErrorResponse.model_dump() 序列化测试。"""

    def test_basic_serialization(self):
        """model_dump() 返回 {"detail": str} 格式。"""
        resp = ErrorResponse(detail="something went wrong")
        dumped = resp.model_dump()
        assert dumped == {"detail": "something went wrong"}

    def test_chinese_detail(self):
        """中文字符串正确序列化。"""
        resp = ErrorResponse(detail="内部错误: ValueError: invalid input")
        dumped = resp.model_dump()
        assert dumped["detail"] == "内部错误: ValueError: invalid input"

    def test_empty_detail(self):
        """空字符串也是合法的 detail。"""
        resp = ErrorResponse(detail="")
        assert resp.model_dump() == {"detail": ""}

    def test_no_extra_fields(self):
        """model_dump() 不包含额外字段。"""
        resp = ErrorResponse(detail="err")
        dumped = resp.model_dump()
        assert set(dumped.keys()) == {"detail"}

    def test_json_serializable(self):
        """model_dump() 结果可以被 json.dumps 序列化。"""
        import json
        resp = ErrorResponse(detail="test error")
        json_str = json.dumps(resp.model_dump(), ensure_ascii=False)
        assert json.loads(json_str) == {"detail": "test error"}


# ============================================================
# GenerateChartWithPromptResponse
# ============================================================

class TestResponseSerialization:
    """GenerateChartWithPromptResponse.model_dump() 序列化测试。"""

    def test_basic_serialization(self):
        """model_dump() 返回 Charts/HtmlFilePaths/AgentLogs 三个字段。"""
        resp = GenerateChartWithPromptResponse(
            Charts=["Bar", "Line"],
            HtmlFilePaths=["/path/to/chart1.html", "/path/to/chart2.html"],
            AgentLogs=["log1", "log2"],
        )
        dumped = resp.model_dump()
        assert dumped == {
            "Charts": ["Bar", "Line"],
            "HtmlFilePaths": ["/path/to/chart1.html", "/path/to/chart2.html"],
            "AgentLogs": ["log1", "log2"],
        }

    def test_empty_lists(self):
        """空列表是合法值。"""
        resp = GenerateChartWithPromptResponse(
            Charts=[], HtmlFilePaths=[], AgentLogs=[]
        )
        dumped = resp.model_dump()
        assert dumped["Charts"] == []
        assert dumped["HtmlFilePaths"] == []
        assert dumped["AgentLogs"] == []

    def test_field_names_preserved(self):
        """字段名大小写保持不变 (Charts 而非 charts)。"""
        resp = GenerateChartWithPromptResponse(
            Charts=["Bar"], HtmlFilePaths=["/a.html"], AgentLogs=["log"]
        )
        dumped = resp.model_dump()
        assert "Charts" in dumped
        assert "HtmlFilePaths" in dumped
        assert "AgentLogs" in dumped
        # 确保不是 snake_case
        assert "charts" not in dumped
        assert "html_file_paths" not in dumped

    def test_no_extra_fields(self):
        """不包含额外字段。"""
        resp = GenerateChartWithPromptResponse(
            Charts=[], HtmlFilePaths=[], AgentLogs=[]
        )
        assert set(resp.model_dump().keys()) == {"Charts", "HtmlFilePaths", "AgentLogs"}


# ============================================================
# GenerateChartWithPromptRequest (反序列化/校验)
# ============================================================

class TestChartRequestValidation:
    """GenerateChartWithPromptRequest 输入校验测试。"""

    def test_minimal_valid(self):
        """只有 user_prompt 也能创建。"""
        req = GenerateChartWithPromptRequest(user_prompt="画图")
        assert req.user_prompt == "画图"
        assert req.file_paths is None
        assert req.db_config is None

    def test_full_valid(self):
        """所有字段都填充。"""
        req = GenerateChartWithPromptRequest(
            file_paths=["/path/a.csv", "/path/b.xlsx"],
            db_config={"host": "localhost"},
            user_prompt="分析数据",
            config='{"type": "bar"}',
            model_url="http://localhost:11434",
            model_type="deepseek",
            model_api_key="sk-xxx",
            api_key="service-key",
            mcp_prompt="mcp",
            skill_prompt="skill",
            viz_mode="chart",
        )
        assert req.file_paths == ["/path/a.csv", "/path/b.xlsx"]
        assert req.db_config == {"host": "localhost"}
        assert req.viz_mode == "chart"

    def test_defaults(self):
        """可选字段使用默认值。"""
        req = GenerateChartWithPromptRequest(user_prompt="test")
        assert req.mcp_prompt == ""
        assert req.skill_prompt == ""
        assert req.viz_mode == "auto"
        assert req.config is None
        assert req.model_url is None

    def test_missing_user_prompt_raises(self):
        """缺少必填字段 user_prompt 应抛出 ValidationError。"""
        with pytest.raises(ValidationError):
            GenerateChartWithPromptRequest()

    def test_model_dump_roundtrip(self):
        """model_dump() -> model_validate() 往返一致。"""
        original = GenerateChartWithPromptRequest(
            file_paths=["/a.csv"],
            user_prompt="test",
            viz_mode="scientific",
        )
        dumped = original.model_dump()
        restored = GenerateChartWithPromptRequest.model_validate(dumped)
        assert restored.file_paths == original.file_paths
        assert restored.user_prompt == original.user_prompt
        assert restored.viz_mode == original.viz_mode


# ============================================================
# CompleteVizCodeRequest
# ============================================================

class TestCodeRequestValidation:
    """CompleteVizCodeRequest 输入校验测试。"""

    def test_valid(self):
        req = CompleteVizCodeRequest(
            code_file_paths=["/main.py"],
            user_prompt="可视化",
        )
        assert req.code_file_paths == ["/main.py"]
        assert req.user_prompt == "可视化"

    def test_missing_code_file_paths_raises(self):
        with pytest.raises(ValidationError):
            CompleteVizCodeRequest(user_prompt="test")

    def test_missing_user_prompt_raises(self):
        with pytest.raises(ValidationError):
            CompleteVizCodeRequest(code_file_paths=["/a.py"])

    def test_empty_list_allowed(self):
        """空列表是合法的 (运行时校验在 API 层)。"""
        req = CompleteVizCodeRequest(code_file_paths=[], user_prompt="x")
        assert req.code_file_paths == []


# ============================================================
# GetChartRequest
# ============================================================

class TestGetChartRequest:
    """GetChartRequest 输入校验测试。"""

    def test_valid(self):
        req = GetChartRequest(chartId="chart_123.html")
        assert req.chartId == "chart_123.html"

    def test_missing_chart_id_raises(self):
        with pytest.raises(ValidationError):
            GetChartRequest()


# ============================================================
# Pydantic V2 弃用警告检查
# ============================================================

class TestNoDeprecationWarnings:
    """确保序列化过程不触发 Pydantic V2 弃用警告。"""

    def test_error_response_no_warning(self):
        """ErrorResponse.model_dump() 不触发弃用警告。"""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            ErrorResponse(detail="test").model_dump()
            pydantic_warnings = [
                x for x in w if "PydanticDeprecatedSince" in str(x.category.__name__)
            ]
            assert len(pydantic_warnings) == 0, "仍有 Pydantic 弃用警告"

    def test_chart_response_no_warning(self):
        """GenerateChartWithPromptResponse.model_dump() 不触发弃用警告。"""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            GenerateChartWithPromptResponse(
                Charts=["Bar"], HtmlFilePaths=["/a.html"], AgentLogs=["log"]
            ).model_dump()
            pydantic_warnings = [
                x for x in w if "PydanticDeprecatedSince" in str(x.category.__name__)
            ]
            assert len(pydantic_warnings) == 0, "仍有 Pydantic 弃用警告"

    def test_request_validation_no_warning(self):
        """GenerateChartWithPromptRequest.model_validate() 不触发弃用警告。"""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            GenerateChartWithPromptRequest.model_validate({"user_prompt": "test"})
            pydantic_warnings = [
                x for x in w if "PydanticDeprecatedSince" in str(x.category.__name__)
            ]
            assert len(pydantic_warnings) == 0, "仍有 Pydantic 弃用警告"
