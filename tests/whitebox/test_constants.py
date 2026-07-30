"""白盒测试：常量和数据模型。

测试 service/constants.py 和 service/viz_data/schema.py。
"""
import pytest

from service.constants import CSV_ENCODINGS
from service.viz_data.adapters.stats_gov_data import (
    CHINA_MACRO_INDICATORS,
    CPI_MONTHLY,
    GDP_QUARTERLY,
    INDUSTRIAL_VALUE_ADDED,
    RETAIL_SALES,
    URBAN_UNEMPLOYMENT,
    get_all_indicator_info,
    get_indicator_data,
)


# ============================================================
# CSV_ENCODINGS 常量
# ============================================================

class TestCsvEncodings:
    """测试 CSV 编码常量（任务9优化）。"""

    def test_not_empty(self):
        """CSV_ENCODINGS 不应为空。"""
        assert len(CSV_ENCODINGS) > 0

    def test_contains_utf8(self):
        """必须包含 utf-8。"""
        assert "utf-8" in CSV_ENCODINGS

    def test_contains_gbk(self):
        """必须包含 gbk（中文 Windows 常见编码）。"""
        assert "gbk" in CSV_ENCODINGS

    def test_contains_gb2312(self):
        """必须包含 gb2312。"""
        assert "gb2312" in CSV_ENCODINGS


# ============================================================
# 国家统计局预置数据完整性
# ============================================================

class TestStatsGovData:
    """测试国家统计局预置数据的完整性。"""

    def test_gdp_quarterly_not_empty(self):
        """GDP 季度数据不应为空。"""
        assert len(GDP_QUARTERLY) > 0
        assert len(GDP_QUARTERLY) >= 40  # 至少 10 年 × 4 季度

    def test_gdp_has_required_fields(self):
        """GDP 数据应包含必要字段。"""
        for row in GDP_QUARTERLY:
            assert "年份" in row
            assert "季度" in row
            assert "GDP_累计值" in row
            assert "GDP_同比" in row

    def test_cpi_monthly_not_empty(self):
        """CPI 月度数据不应为空。"""
        assert len(CPI_MONTHLY) > 0
        assert len(CPI_MONTHLY) >= 36  # 至少 3 年 × 12 月

    def test_cpi_has_required_fields(self):
        """CPI 数据应包含必要字段。"""
        for row in CPI_MONTHLY[:5]:
            assert "年份" in row
            assert "月份" in row
            assert "CPI_同比" in row

    def test_industrial_value_added_not_empty(self):
        """工业增加值数据不应为空。"""
        assert len(INDUSTRIAL_VALUE_ADDED) > 0

    def test_retail_sales_not_empty(self):
        """社零数据不应为空。"""
        assert len(RETAIL_SALES) > 0

    def test_urban_unemployment_not_empty(self):
        """失业率数据不应为空。"""
        assert len(URBAN_UNEMPLOYMENT) > 0

    def test_get_indicator_data_valid(self):
        """get_indicator_data 应返回正确数据。"""
        data = get_indicator_data("GDP_QUARTERLY")
        assert data == GDP_QUARTERLY

    def test_get_indicator_data_invalid(self):
        """get_indicator_data 对无效代码应返回空列表。"""
        data = get_indicator_data("INVALID_CODE")
        assert data == []

    def test_get_all_indicator_info(self):
        """get_all_indicator_info 应返回指标元信息列表。"""
        info = get_all_indicator_info()
        assert len(info) >= 5  # 至少 5 个指标
        codes = [i["code"] for i in info]
        assert "GDP_QUARTERLY" in codes
        assert "CPI_MONTHLY" in codes

    def test_indicator_info_has_required_fields(self):
        """每个指标元信息应包含必要字段。"""
        for info in CHINA_MACRO_INDICATORS:
            assert "code" in info
            assert "name" in info
            assert "category" in info
            assert "description" in info
            assert "data_key" in info
