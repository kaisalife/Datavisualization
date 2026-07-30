"""白盒测试：工具函数。

测试 service/utils.py 的 JSON 提取和代码提取逻辑。
"""
import pytest

from service.utils import (
    extract_code_from_response,
    extract_json_from_response,
    _find_balanced_json,
    _try_load_json,
)


# ============================================================
# extract_json_from_response
# ============================================================

class TestExtractJson:
    """测试 JSON 提取逻辑。"""

    def test_valid_json_in_markdown_fence(self):
        """markdown json 围栏中的 JSON 应正确提取。"""
        text = '```json\n{"key": "value"}\n```'
        result = extract_json_from_response(text)
        assert result == {"key": "value"}

    def test_plain_json_without_fence(self):
        """无围栏的纯 JSON 应正确提取。"""
        text = '{"plan_id": "1", "chart_type": "Bar"}'
        result = extract_json_from_response(text)
        assert result is not None
        assert result["plan_id"] == "1"
        assert result["chart_type"] == "Bar"

    def test_json_with_surrounding_text(self):
        """JSON 前后有说明文字时应提取 JSON。"""
        text = '这是分析结果：\n{"plans": [{"plan_id": "1"}]}\n以上是计划。'
        result = extract_json_from_response(text)
        assert result is not None
        assert "plans" in result
        assert len(result["plans"]) == 1

    @pytest.mark.xfail(reason="_try_load_json 中 }} -> } 替换会破坏深层嵌套 JSON 的结尾，已知 bug")
    def test_nested_json(self):
        """嵌套 JSON 应正确提取（栈匹配）。

        已知问题：_try_load_json 中的 replace('}}', '}')
        会把 }}} 错误缩减为 }}，导致 json.loads 失败。
        """
        text = '{"outer": {"inner": {"deep": "value"}}}'
        result = extract_json_from_response(text)
        assert result is not None
        assert result["outer"]["inner"]["deep"] == "value"

    def test_json_with_braces_in_string(self):
        """字符串内含花括号不应破坏栈匹配。"""
        text = '{"desc": "函数 {test} 的结果"}'
        result = extract_json_from_response(text)
        assert result is not None
        assert result["desc"] == "函数 {test} 的结果"

    def test_double_brace_escape(self):
        """双花括号转义应被正确处理。"""
        text = '{"key": "value"}}'
        result = extract_json_from_response(text)
        # 宽容处理
        assert result is not None

    def test_empty_string_returns_none(self):
        """空字符串应返回 None。"""
        assert extract_json_from_response("") is None

    def test_no_json_returns_none(self):
        """无 JSON 内容应返回 None。"""
        assert extract_json_from_response("这是一段普通文字") is None


# ============================================================
# _find_balanced_json
# ============================================================

class TestFindBalancedJson:
    """测试栈匹配 JSON 提取（任务7优化）。"""

    def test_simple_object(self):
        """简单对象应匹配。"""
        result = _find_balanced_json('{"a": 1}')
        assert result == '{"a": 1}'

    def test_nested_object(self):
        """嵌套对象应正确匹配外层。"""
        result = _find_balanced_json('{"a": {"b": 2}}')
        assert result == '{"a": {"b": 2}}'

    def test_brace_in_string(self):
        """字符串内的花括号不应影响匹配。"""
        result = _find_balanced_json('{"desc": "a { b } c"}')
        assert result is not None
        assert "a { b } c" in result

    def test_escaped_quote_in_string(self):
        """转义引号不应中断字符串识别。"""
        result = _find_balanced_json(r'{"path": "C:\\folder\\"}')
        assert result is not None

    def test_no_brace_returns_none(self):
        """无花括号应返回 None。"""
        assert _find_balanced_json("no braces here") is None


# ============================================================
# extract_code_from_response
# ============================================================

class TestExtractCode:
    """测试代码提取逻辑。"""

    def test_python_fence(self):
        """python 围栏中的代码应正确提取。"""
        text = '```python\nprint("hello")\n```'
        result = extract_code_from_response(text)
        assert "print" in result
        assert "hello" in result

    def test_generic_fence(self):
        """无语言标记的围栏也应提取。"""
        text = '```\nprint("hello")\n```'
        result = extract_code_from_response(text)
        assert "print" in result

    def test_no_fence_returns_raw(self):
        """无围栏时返回原始文本。"""
        text = 'print("hello")'
        result = extract_code_from_response(text)
        assert result == text

    def test_code_with_imports(self):
        """含 import 语句的代码应完整提取。"""
        text = '```python\nimport pandas as pd\ndf = pd.read_csv("data.csv")\n```'
        result = extract_code_from_response(text)
        assert "import pandas" in result
        assert "read_csv" in result
