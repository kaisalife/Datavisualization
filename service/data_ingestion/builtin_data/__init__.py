"""内置数据文件包。

集中存放不依赖外部模块的预置数据：
- 国家统计局宏观数据（stats_gov_data）
- 世界银行指标常量与 LLM 选择函数（worldbank_constants）
"""
from service.data_ingestion.builtin_data.stats_gov_data import (
    CHINA_MACRO_INDICATORS,
    CPI_MONTHLY,
    GDP_QUARTERLY,
    INDUSTRIAL_VALUE_ADDED,
    RETAIL_SALES,
    URBAN_UNEMPLOYMENT,
    _DATA_MAP,
    get_all_indicator_info,
    get_indicator_data,
)
from service.data_ingestion.builtin_data.worldbank_constants import (
    _COMMON_INDICATORS,
    _COUNTRY_MAP,
    _INDICATOR_DESCRIPTIONS,
    select_indicators_with_llm,
)

__all__ = [
    # 国家统计局数据
    "GDP_QUARTERLY",
    "CPI_MONTHLY",
    "INDUSTRIAL_VALUE_ADDED",
    "RETAIL_SALES",
    "URBAN_UNEMPLOYMENT",
    "CHINA_MACRO_INDICATORS",
    "_DATA_MAP",
    "get_indicator_data",
    "get_all_indicator_info",
    # 世界银行常量与函数
    "_COMMON_INDICATORS",
    "_COUNTRY_MAP",
    "_INDICATOR_DESCRIPTIONS",
    "select_indicators_with_llm",
]
