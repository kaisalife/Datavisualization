"""白盒测试：数据预览与质量检查。

测试 service/viz_data/cleaning/preview.py 的：
- generate_preview(): 列统计、样本行、质量指标
- DataQualityChecker.check(): 5 项硬规则检查
- DataPreview.to_dict() / to_prompt_text()
- 边界情况：空 DataFrame、list/dict 列、中文列名、混合类型
"""
from __future__ import annotations

import pandas as pd
import pytest

from service.viz_data.cleaning.preview import (
    ColumnStat,
    DataPreview,
    DataQualityChecker,
    QualityIssue,
    QualityMetrics,
    QualityResult,
    _is_chinese,
    _safe_str,
    generate_preview,
)


# ============================================================
# _is_chinese / _safe_str
# ============================================================

class TestIsChinese:
    """测试中文检测。"""

    def test_chinese_string(self):
        assert _is_chinese("销售额") is True

    def test_mixed_string(self):
        assert _is_chinese("销售额amount") is True

    def test_english_string(self):
        assert _is_chinese("amount") is False

    def test_empty_string(self):
        assert _is_chinese("") is False

    def test_non_string_input(self):
        assert _is_chinese(123) is False


class TestSafeStr:
    """测试安全转字符串。"""

    def test_none(self):
        assert _safe_str(None) == "null"

    def test_nan(self):
        assert _safe_str(float("nan")) == "null"

    def test_string(self):
        assert _safe_str("hello") == "hello"

    def test_int(self):
        assert _safe_str(42) == "42"

    def test_float(self):
        assert _safe_str(3.14) == "3.14"


# ============================================================
# generate_preview
# ============================================================

class TestGeneratePreview:
    """测试数据预览生成。"""

    def test_basic_dataframe(self):
        """基本 DataFrame 应正确生成预览。"""
        df = pd.DataFrame({
            "id": [1, 2, 3],
            "name": ["Alice", "Bob", "Charlie"],
        })
        preview = generate_preview(df, "test")
        assert preview.name == "test"
        assert preview.row_count == 3
        assert preview.column_count == 2
        assert len(preview.columns) == 2
        assert len(preview.sample_rows) == 3

    def test_empty_dataframe(self):
        """空 DataFrame 不崩溃。"""
        df = pd.DataFrame()
        preview = generate_preview(df, "empty")
        assert preview.row_count == 0
        assert preview.column_count == 0
        assert preview.quality_metrics.overall_null_rate == 0.0
        assert preview.quality_metrics.dup_row_rate == 0.0

    def test_with_nulls(self):
        """含空值的数据应正确计算空值率。"""
        df = pd.DataFrame({
            "a": [1, None, 3],
            "b": ["x", "y", None],
        })
        preview = generate_preview(df, "nulls")
        assert preview.quality_metrics.overall_null_rate > 0
        # 6 个单元格中 2 个为空
        assert pytest.approx(preview.quality_metrics.overall_null_rate, rel=0.01) == 2 / 6

    def test_with_duplicates(self):
        """含重复行的数据应正确计算重复率。"""
        df = pd.DataFrame({
            "a": [1, 1, 2, 2],
            "b": ["x", "x", "y", "y"],
        })
        preview = generate_preview(df, "dups")
        assert preview.quality_metrics.dup_row_rate == 0.5

    def test_chinese_columns(self):
        """中文列名应被检测到。"""
        df = pd.DataFrame({"销售额": [100, 200], "日期": ["2024", "2025"]})
        preview = generate_preview(df, "chinese")
        assert preview.quality_metrics.has_chinese_columns is True

    def test_english_columns(self):
        """英文列名不应触发中文检测。"""
        df = pd.DataFrame({"amount": [100, 200], "date": ["2024", "2025"]})
        preview = generate_preview(df, "english")
        assert preview.quality_metrics.has_chinese_columns is False

    def test_mixed_dtypes(self):
        """混合类型列应被检测到。"""
        df = pd.DataFrame({"col": [1, "two", 3, "four"]})
        preview = generate_preview(df, "mixed")
        assert preview.quality_metrics.has_mixed_dtypes is True

    def test_empty_rows(self):
        """全空行应被检测到。"""
        df = pd.DataFrame({
            "a": [1, None, 3],
            "b": ["x", None, "z"],
        })
        preview = generate_preview(df, "empty_row")
        assert preview.quality_metrics.has_empty_rows is True

    def test_no_empty_rows(self):
        """无全空行时不应检测到。"""
        df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
        preview = generate_preview(df, "no_empty")
        assert preview.quality_metrics.has_empty_rows is False

    def test_list_column(self):
        """含 list 的列不应崩溃（TypeError 降级）。"""
        df = pd.DataFrame({
            "tags": [["a", "b"], ["c"], ["a", "b"]],
            "id": [1, 2, 3],
        })
        preview = generate_preview(df, "list_col")
        assert preview.row_count == 3
        # list 列的 nunique 应通过 str() 降级处理
        col = next(c for c in preview.columns if c.name == "tags")
        assert col.unique_count > 0

    def test_dict_column(self):
        """含 dict 的列不应崩溃。"""
        df = pd.DataFrame({
            "meta": [{"k": 1}, {"k": 2}, {"k": 1}],
            "id": [1, 2, 3],
        })
        preview = generate_preview(df, "dict_col")
        assert preview.row_count == 3

    def test_list_column_dup_rate(self):
        """含 list 列时 duplicated 不崩溃。

        pandas 3.0 能处理 list 列的 duplicated()，不再触发 TypeError 降级。
        """
        df = pd.DataFrame({
            "tags": [["a"], ["a"], ["b"]],
        })
        preview = generate_preview(df, "list_dup")
        # 不崩溃即通过（值可能因 pandas 版本而异）
        assert preview.quality_metrics.dup_row_rate >= 0.0

    def test_sample_size(self):
        """sample_size 参数应限制样本行数。"""
        df = pd.DataFrame({"a": list(range(20))})
        preview = generate_preview(df, "sample", sample_size=5)
        assert len(preview.sample_rows) == 5

    def test_column_stat_null_rate(self):
        """列空值率应正确计算。"""
        df = pd.DataFrame({
            "full": [1, 2, 3, 4],
            "sparse": [1, None, None, 4],
        })
        preview = generate_preview(df, "null_rates")
        full_col = next(c for c in preview.columns if c.name == "full")
        sparse_col = next(c for c in preview.columns if c.name == "sparse")
        assert full_col.null_rate == 0.0
        assert sparse_col.null_rate == 0.5

    def test_column_stat_sample_values(self):
        """列样本值应正确提取。"""
        df = pd.DataFrame({"name": ["Alice", "Bob", "Charlie"]})
        preview = generate_preview(df, "samples")
        col = preview.columns[0]
        assert "Alice" in col.sample_values


# ============================================================
# DataPreview 序列化
# ============================================================

class TestDataPreviewSerialization:
    """测试 DataPreview 的序列化方法。"""

    def test_to_dict(self):
        """to_dict 应返回正确的字典结构。"""
        df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
        preview = generate_preview(df, "test")
        d = preview.to_dict()
        assert d["name"] == "test"
        assert d["row_count"] == 2
        assert d["column_count"] == 2
        assert len(d["columns"]) == 2
        assert "quality_metrics" in d

    def test_to_prompt_text(self):
        """to_prompt_text 应包含关键信息。"""
        df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
        preview = generate_preview(df, "test")
        text = preview.to_prompt_text()
        assert "test" in text
        assert "行数: 2" in text
        assert "列数: 2" in text
        assert "质量指标" in text


# ============================================================
# DataQualityChecker
# ============================================================

class TestDataQualityChecker:
    """测试硬规则质量检查器。"""

    def test_clean_data(self):
        """干净数据应返回 is_clean=True。"""
        df = pd.DataFrame({
            "id": [1, 2, 3, 4, 5],
            "name": ["a", "b", "c", "d", "e"],
            "score": [85.0, 72.0, 90.0, 65.0, 88.0],
        })
        preview = generate_preview(df, "clean")
        result = DataQualityChecker.check(preview)
        assert result.is_clean is True
        assert len(result.issues) == 0

    def test_high_null_rate(self):
        """高空值率应触发 warning。"""
        df = pd.DataFrame({
            "a": [1, None, None, None, None],
            "b": [1, 2, 3, 4, 5],
        })
        preview = generate_preview(df, "nulls")
        result = DataQualityChecker.check(preview)
        assert not result.is_clean
        null_issues = [i for i in result.issues if i.type == "high_null_rate"]
        assert len(null_issues) == 1
        assert null_issues[0].severity == "warning"

    def test_high_dup_rate(self):
        """高重复率应触发 warning。"""
        df = pd.DataFrame({
            "a": [1, 1, 1, 1, 1],
            "b": ["x", "x", "x", "x", "x"],
        })
        preview = generate_preview(df, "dups")
        result = DataQualityChecker.check(preview)
        dup_issues = [i for i in result.issues if i.type == "high_dup_rate"]
        assert len(dup_issues) == 1

    def test_chinese_column_names(self):
        """中文列名应触发 error。"""
        df = pd.DataFrame({"销售额": [100, 200], "日期": ["a", "b"]})
        preview = generate_preview(df, "chinese")
        result = DataQualityChecker.check(preview)
        assert not result.is_clean
        cn_issues = [i for i in result.issues if i.type == "non_standard_columns"]
        assert len(cn_issues) == 1
        assert cn_issues[0].severity == "error"
        assert "销售额" in cn_issues[0].affected_columns

    def test_mixed_dtypes(self):
        """混合类型应触发 error。"""
        df = pd.DataFrame({"col": [1, "two", 3, "four", 5]})
        preview = generate_preview(df, "mixed")
        result = DataQualityChecker.check(preview)
        mixed_issues = [i for i in result.issues if i.type == "mixed_dtypes"]
        assert len(mixed_issues) == 1
        assert mixed_issues[0].severity == "error"

    def test_empty_rows(self):
        """全空行应触发 warning。"""
        df = pd.DataFrame({
            "a": [1, None, 3],
            "b": ["x", None, "z"],
        })
        preview = generate_preview(df, "empty_row")
        result = DataQualityChecker.check(preview)
        empty_issues = [i for i in result.issues if i.type == "empty_rows"]
        assert len(empty_issues) == 1
        assert empty_issues[0].severity == "warning"

    def test_custom_thresholds(self):
        """自定义阈值应生效。"""
        df = pd.DataFrame({
            "a": [1, 2, 3, 4, 5, None],  # 1/6 ≈ 16.7% 空值
            "b": [1, 2, 3, 4, 5, 6],
        })
        preview = generate_preview(df, "custom")

        # 默认阈值 5% -> 应报
        result_default = DataQualityChecker.check(preview)
        assert any(i.type == "high_null_rate" for i in result_default.issues)

        # 提高阈值到 20% -> 不报
        original = DataQualityChecker.NULL_RATE_THRESHOLD
        try:
            DataQualityChecker.NULL_RATE_THRESHOLD = 0.20
            result_relaxed = DataQualityChecker.check(preview)
            assert not any(i.type == "high_null_rate" for i in result_relaxed.issues)
        finally:
            DataQualityChecker.NULL_RATE_THRESHOLD = original

    def test_multiple_issues(self):
        """多种问题应同时检测到。"""
        df = pd.DataFrame({
            "销售额": [100, 100, None, None, None],  # 中文列名 + 高空值 + 重复
        })
        preview = generate_preview(df, "multi")
        result = DataQualityChecker.check(preview)
        assert not result.is_clean
        types = {i.type for i in result.issues}
        assert "non_standard_columns" in types
        assert "high_null_rate" in types

    def test_quality_result_to_dict(self):
        """QualityResult.to_dict() 应正确序列化。"""
        df = pd.DataFrame({"销售额": [None, None, None]})
        preview = generate_preview(df, "test")
        result = DataQualityChecker.check(preview)
        d = result.to_dict()
        assert "is_clean" in d
        assert "issues" in d

    def test_quality_result_to_prompt_text(self):
        """QualityResult.to_prompt_text() 应返回文本。"""
        df = pd.DataFrame({"销售额": [None, None, None]})
        preview = generate_preview(df, "test")
        result = DataQualityChecker.check(preview)
        text = result.to_prompt_text()
        assert "质量问题" in text or "良好" in text
