"""黑盒测试：端到端（E2E）。

测试完整的数据可视化管线：数据输入 -> Adapter -> 图表生成 -> HTML 输出。
LLM 部分使用 mock，验证管线逻辑和最终产物。
"""
import asyncio
from pathlib import Path

import pandas as pd
import pytest

from service.viz_data.adapters.stats_gov_data import (
    GDP_QUARTERLY,
    CPI_MONTHLY,
    get_indicator_data,
)


# ============================================================
# 国家统计局数据 E2E（直接验证数据，不通过抽象 Adapter）
# ============================================================

class TestStatsGovDataE2E:
    """国家统计局预置数据端到端验证。"""

    def test_gdp_data_can_load_to_dataframe(self):
        """GDP 数据应能成功加载为 DataFrame。"""
        df = pd.DataFrame(GDP_QUARTERLY)
        assert len(df) > 0
        assert "年份" in df.columns
        assert "GDP_累计值" in df.columns
        assert "GDP_同比" in df.columns

    def test_cpi_data_can_load_to_dataframe(self):
        """CPI 数据应能成功加载为 DataFrame。"""
        df = pd.DataFrame(CPI_MONTHLY)
        assert len(df) > 0
        assert "CPI_同比" in df.columns

    def test_year_filter_on_dataframe(self):
        """年份过滤应正确工作。"""
        df = pd.DataFrame(GDP_QUARTERLY)
        filtered = df[(df["年份"] >= 2023) & (df["年份"] <= 2024)]
        assert len(filtered) > 0
        assert filtered["年份"].min() >= 2023
        assert filtered["年份"].max() <= 2024

    def test_all_indicators_have_data(self):
        """所有注册的指标都应有非空数据。"""
        from service.viz_data.adapters.stats_gov_data import CHINA_MACRO_INDICATORS
        for info in CHINA_MACRO_INDICATORS:
            data = get_indicator_data(info["code"])
            assert len(data) > 0, f"指标 {info['code']} 数据为空"


# ============================================================
# CSV 编码兼容性 E2E
# ============================================================

class TestCSVEncodingE2E:
    """CSV 编码兼容性测试。"""

    def test_utf8_csv_reads_correctly(self, tmp_csv):
        """UTF-8 CSV 应正确读取。"""
        df = pd.read_csv(tmp_csv, encoding="utf-8")
        assert len(df) == 5
        assert "month" in df.columns
        assert "sales" in df.columns

    def test_gbk_csv_reads_with_correct_encoding(self, tmp_csv_gbk):
        """GBK CSV 应用 gbk 编码读取。"""
        df = pd.read_csv(tmp_csv_gbk, encoding="gbk")
        assert len(df) == 3
        assert "月份" in df.columns

    def test_csv_encodings_constant_covers_common_cases(self):
        """CSV_ENCODINGS 常量应覆盖常见编码。"""
        from service.constants import CSV_ENCODINGS
        for enc in ["utf-8", "gbk", "gb2312", "gb18030"]:
            assert enc in CSV_ENCODINGS, f"缺少常见编码: {enc}"


# ============================================================
# 报告生成 E2E（mock LLM）
# ============================================================

class TestReportGenerationE2E:
    """报告生成端到端测试（mock LLM）。"""

    def test_china_macro_report_generates_html(self, mock_llm, tmp_path):
        """中国宏观报告应生成 HTML 文件。"""
        from service.report_pipeline import _generate_china_macro_report

        result = asyncio.run(_generate_china_macro_report(
            user_prompt="分析中国GDP",
            llm_client=mock_llm,
            output_path=str(tmp_path / "test_report.html"),
            start_year=2022,
        ))

        assert result["success"]
        assert Path(result["report_path"]).exists()
        # HTML 文件应大于 1KB
        assert Path(result["report_path"]).stat().st_size > 1000

    def test_report_contains_disclaimer(self, mock_llm, tmp_path):
        """报告应包含免责声明。"""
        from service.report_pipeline import _generate_china_macro_report

        result = asyncio.run(_generate_china_macro_report(
            user_prompt="分析中国GDP",
            llm_client=mock_llm,
            output_path=str(tmp_path / "test_disclaimer.html"),
            start_year=2022,
        ))

        if result["success"]:
            html = Path(result["report_path"]).read_text(encoding="utf-8")
            # 应包含免责声明相关文字
            assert any(kw in html for kw in ["免责", "声明", "仅供参考", "不构成"])
