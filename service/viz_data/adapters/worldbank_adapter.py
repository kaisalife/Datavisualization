"""世界银行 Open Data Adapter。

世界银行 API 文档：https://data.worldbank.org/developers

100% 合法、免费、无需申请 API Key。
覆盖 200+ 国家，15000+ 指标：
- GDP、人均 GDP、GDP 增长率
- 人口、人口增长率、城镇化率
- CPI、通胀率
- 人均收入、消费支出
- 进出口额
- 等等

使用示例：
    adapter = WorldBankAdapter()
    # 查中国历年 GDP
    dataset = await adapter.fetch_indicator("NY.GDP.MKTP.CD", country="CN", start_year=2010, end_year=2025)
    # 搜索指标关键词
    indicators = await adapter.search_indicators("GDP")
"""
from __future__ import annotations

import asyncio
from typing import Optional, List, Dict, Any

import pandas as pd
import aiohttp

from service.viz_data.adapters.base import VizDataAdapter
from service.viz_data.capabilities import AdapterCapabilities
from service.viz_data.schema import DataRef, TabularBlock, VizDataset
from service.viz_data.source_descriptor import SourceDescriptor
from service.viz_data.storage import new_dataset_dir, save_dataframe_to_parquet


# 常用指标对照表（用户说"GDP"，我们知道对应哪个指标代码）
_COMMON_INDICATORS = {
    # GDP 相关
    "GDP": "NY.GDP.MKTP.CD",                    # GDP（现价美元）
    "GDP_PPP": "NY.GDP.MKTP.PP.CD",             # GDP PPP（现价国际元）
    "GDP_GROWTH": "NY.GDP.MKTP.KD.ZG",          # GDP 增长率（年 %）
    "GDP_PER_CAPITA": "NY.GDP.PCAP.CD",         # 人均 GDP（现价美元）
    
    # 人口相关
    "POPULATION": "SP.POP.TOTL",                # 总人口
    "POPULATION_GROWTH": "SP.POP.GROW",         # 人口增长率（年 %）
    "URBAN_POPULATION": "SP.URB.TOTL.IN.ZS",    # 城镇人口占比（%）
    
    # 价格相关
    "CPI": "FP.CPI.TOTL.ZG",                    # CPI 通胀率（年 %）
    
    # 收入相关
    "GNI_PER_CAPITA": "NY.GNP.PCAP.CD",         # 人均 GNI（现价美元）
    "HOUSEHOLD_CONSUMPTION": "NE.CON.PRVT.ZS",  # 居民消费支出占 GDP 比例（%）
    
    # 贸易相关
    "EXPORT": "NE.EXP.GNFS.ZS",                 # 出口占 GDP 比例（%）
    "IMPORT": "NE.IMP.GNFS.ZS",                 # 进口占 GDP 比例（%）
    "TRADE": "NE.TRD.GNFS.ZS",                  # 贸易总额占 GDP 比例（%）
    
    # 就业相关
    "UNEMPLOYMENT": "SL.UEM.TOTL.ZS",           # 失业率（%）
}


class WorldBankAdapter(VizDataAdapter):
    """世界银行 Open Data 适配器。
    
    无需 API Key，完全免费，数据可追溯到 1960 年。
    """
    
    BASE_URL = "http://api.worldbank.org/v2"
    SOURCE_NAME = "世界银行（World Bank Open Data）"
    
    def __init__(
        self,
        indicator: str = "NY.GDP.MKTP.CD",
        country: str = "CN",
        start_year: int = 2010,
        end_year: Optional[int] = None,
    ):
        """
        Args:
            indicator: 指标代码（见 _COMMON_INDICATORS 对照表）
            country: 国家代码（2 字母，如 CN=中国，US=美国，JP=日本）
            start_year: 起始年份
            end_year: 结束年份（默认当前年）
        """
        self.indicator = indicator
        self.country = country.upper()
        self.start_year = start_year
        self.end_year = end_year or pd.Timestamp.now().year
    
    def source_kind(self) -> str:
        return "api"
    
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(needs_llm=False, supports_multi_query=True)
    
    async def fetch(self, engine=None) -> VizDataset:
        """获取数据并组装成 VizDataset。"""
        df = await self._fetch_indicator_data()
        
        # 落盘
        dataset_dir = new_dataset_dir()
        if isinstance(dataset_dir, tuple):
            dataset_dir = dataset_dir[1]
        parquet_path = save_dataframe_to_parquet(df, dataset_dir, "worldbank_data")
        
        # 构建 VizDataset
        columns = dataframe_to_column_schemas(df)
        preview_rows = [df.columns.tolist()] + df.head(10).fillna("").values.tolist()
        
        tabular = TabularBlock(
            columns=columns,
            row_count=len(df),
            preview_rows=preview_rows,
            data_ref=DataRef(
                kind="parquet",
                path=str(parquet_path.resolve()),
                size_bytes=parquet_path.stat().st_size,
            ),
        )
        
        indicator_name = self._get_indicator_name(self.indicator)
        
        return VizDataset(
            dataset_id=f"worldbank_{self.indicator}_{self.country}",
            name=f"{indicator_name}（{self.country}）",
            source_kind="api",
            tabular=tabular,
            descriptor=SourceDescriptor(
                kind="api",
                label=f"世界银行：{indicator_name}",
                logical_id=f"worldbank_{self.indicator}_{self.country}",
                extra={
                    "source": self.SOURCE_NAME,
                    "indicator": self.indicator,
                    "country": self.country,
                    "years": f"{self.start_year}-{self.end_year}",
                    "rows": len(df),
                },
            ),
        )
    
    async def _fetch_indicator_data(self) -> pd.DataFrame:
        """调用世界银行 API 获取指标数据。"""
        url = f"{self.BASE_URL}/country/{self.country}/indicator/{self.indicator}"
        params = {
            "format": "json",
            "date": f"{self.start_year}:{self.end_year}",
            "per_page": 100,
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    raise Exception(f"世界银行 API 调用失败：HTTP {resp.status}")
                
                data = await resp.json()
                if len(data) < 2:
                    return pd.DataFrame()
                
                # data[0] 是元信息，data[1] 是数据数组
                records = data[1]
                if not records:
                    return pd.DataFrame()
        
        # 解析成 DataFrame
        rows = []
        for item in records:
            value = item.get("value")
            if value is None:
                continue  # 跳过空值
            rows.append({
                "年份": int(item["date"]),
                "国家代码": item["countryiso3code"],
                "国家": item["country"]["value"],
                "指标代码": item["indicator"]["id"],
                "指标名称": item["indicator"]["value"],
                "数值": float(value),
                "单位": "美元" if "GDP" in self.indicator else 
                        "%" if "ZG" in self.indicator or "ZS" in self.indicator else 
                        "人" if "POP" in self.indicator else "",
                "数据来源": self.SOURCE_NAME,
            })
        
        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.sort_values("年份").reset_index(drop=True)
        
        return df
    
    @classmethod
    async def search_indicators(cls, keyword: str, limit: int = 20) -> List[Dict[str, str]]:
        """搜索指标（供 LLM 选择用）。
        
        Args:
            keyword: 关键词，如 "GDP"、"人口"、"通胀"
            limit: 返回结果数量
            
        Returns:
            [{ "id": "NY.GDP.MKTP.CD", "name": "GDP（现价美元）" }]
        """
        url = f"{cls.BASE_URL}/indicator"
        params = {
            "format": "json",
            "per_page": 100,
            "page": 1,
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                if len(data) < 2:
                    return []
                indicators = data[1]
        
        # 关键词过滤
        keyword = keyword.lower()
        results = []
        for ind in indicators:
            name = ind.get("name", "")
            if keyword in name.lower():
                results.append({
                    "id": ind["id"],
                    "name": name,
                })
                if len(results) >= limit:
                    break
        
        return results
    
    @staticmethod
    def resolve_indicator(keyword: str) -> Optional[str]:
        """把用户说的关键词映射成指标代码（简单规则版，LLM 版可更智能）。"""
        keyword = keyword.upper().strip()
        
        # 精确匹配
        if keyword in _COMMON_INDICATORS:
            return _COMMON_INDICATORS[keyword]
        
        # 模糊匹配
        for key, code in _COMMON_INDICATORS.items():
            if keyword in key or key in keyword:
                return code
        
        return None
    
    def _get_indicator_name(self, indicator_code: str) -> str:
        """从代码反查指标名。"""
        for name, code in _COMMON_INDICATORS.items():
            if code == indicator_code:
                return name
        return indicator_code

    def normalize(self, raw):
        """Phase 2: fetch 已完成全部工作，normalize 直接返回。"""
        return raw


# 从 df_stats 导入（放在末尾避免循环导入）
from service.introspection.df_stats import dataframe_to_column_schemas


# ============================================================
# LLM 指标智能选择
# ============================================================

# 给 LLM 看的指标说明列表（中文描述，方便 LLM 理解选择）
_INDICATOR_DESCRIPTIONS = [
    {
        "code": "NY.GDP.MKTP.CD",
        "name_en": "GDP (current US$)",
        "name_cn": "GDP（现价美元）",
        "category": "经济总量",
        "description": "国内生产总值，衡量一个国家经济规模的核心指标",
    },
    {
        "code": "NY.GDP.PCAP.CD",
        "name_en": "GDP per capita (current US$)",
        "name_cn": "人均GDP（现价美元）",
        "category": "经济总量",
        "description": "人均国内生产总值，反映国民富裕程度",
    },
    {
        "code": "NY.GDP.MKTP.KD.ZG",
        "name_en": "GDP growth (annual %)",
        "name_cn": "GDP增长率（年度%）",
        "category": "经济增长",
        "description": "GDP同比增长率，反映经济增速",
    },
    {
        "code": "SP.POP.TOTL",
        "name_en": "Population, total",
        "name_cn": "总人口",
        "category": "人口",
        "description": "国家总人口数",
    },
    {
        "code": "SP.POP.GROW",
        "name_en": "Population growth (annual %)",
        "name_cn": "人口增长率（年度%）",
        "category": "人口",
        "description": "人口年度增长率",
    },
    {
        "code": "SP.URB.TOTL.IN.ZS",
        "name_en": "Urban population (% of total)",
        "name_cn": "城镇人口占比（%）",
        "category": "人口",
        "description": "城镇人口占总人口的比例，反映城镇化水平",
    },
    {
        "code": "FP.CPI.TOTL.ZG",
        "name_en": "Inflation, consumer prices (annual %)",
        "name_cn": "CPI通胀率（年度%）",
        "category": "价格",
        "description": "居民消费价格指数涨幅，反映通货膨胀水平",
    },
    {
        "code": "NE.EXP.GNFS.ZS",
        "name_en": "Exports of goods and services (% of GDP)",
        "name_cn": "出口占GDP比例（%）",
        "category": "贸易",
        "description": "货物和服务出口占GDP的比重",
    },
    {
        "code": "NE.IMP.GNFS.ZS",
        "name_en": "Imports of goods and services (% of GDP)",
        "name_cn": "进口占GDP比例（%）",
        "category": "贸易",
        "description": "货物和服务进口占GDP的比重",
    },
    {
        "code": "NE.TRD.GNFS.ZS",
        "name_en": "Trade (% of GDP)",
        "name_cn": "贸易总额占GDP比例（%）",
        "category": "贸易",
        "description": "进出口总额占GDP的比重，反映外贸依存度",
    },
    {
        "code": "SL.UEM.TOTL.ZS",
        "name_en": "Unemployment, total (% of total labor force)",
        "name_cn": "失业率（%）",
        "category": "就业",
        "description": "总失业率，反映劳动力市场状况",
    },
]


_COUNTRY_MAP = {
    "CN": "中国",
    "US": "美国",
    "JP": "日本",
    "DE": "德国",
    "GB": "英国",
    "FR": "法国",
    "IN": "印度",
    "BR": "巴西",
    "RU": "俄罗斯",
    "KR": "韩国",
    "AU": "澳大利亚",
    "CA": "加拿大",
    "IT": "意大利",
    "MX": "墨西哥",
    "ES": "西班牙",
    "ID": "印度尼西亚",
    "NL": "荷兰",
    "CH": "瑞士",
    "SA": "沙特阿拉伯",
    "TR": "土耳其",
}


_INDICATOR_SELECT_PROMPT = """
你是一位宏观经济数据专家，请根据用户的需求，选择国家和指标。

可用国家（2 字母代码）：
{countries_json}

可选指标列表（JSON格式）：
{indicators_json}

用户需求：{user_prompt}

选择规则：
1. 指标：最多选 3 个，优先核心常用指标，避免高度相关重复
2. 国家：最多选 3 个（支持跨国对比，如"中美"→CN,US），没提到国家时默认中国（CN）
3. 如果用户说"对比"、"横向比较"等，自动选 2-3 个最相关的国家进行对比

返回严格JSON格式，不要其他文字：
{{
    "countries": [
        {{"code": "CN", "name": "中国"}},
        {{"code": "US", "name": "美国"}}
    ],
    "indicators": [
        {{"code": "NY.GDP.MKTP.CD", "name": "GDP（现价美元）", "reason": "..."}}
    ],
    "is_compare_mode": true,
    "explanation": "一句话说明选择思路"
}}
"""


async def select_indicators_with_llm(
    user_prompt: str,
    llm_client,
    max_indicators: int = 3,
    max_countries: int = 3,
) -> dict:
    """根据用户自然语言需求，智能选择国家和指标（支持多国家对比）。
    
    Args:
        user_prompt: 用户需求（如 "分析中国 GDP、人口和通胀趋势" / "对比中美 GDP"）
        llm_client: LLM 客户端（需支持 ainvoke 方法）
        max_indicators: 最多选择的指标数量
        max_countries: 最多选择的国家数量
    
    Returns:
        {
            "countries": [{"code": "CN", "name": "中国"}, ...],
            "indicators": [...],
            "is_compare_mode": true/false,
            "explanation": "...",
        }
    """
    # 准备指标列表（只保留必要字段给 LLM）
    indicators_for_llm = [
        {
            "code": ind["code"],
            "name_cn": ind["name_cn"],
            "category": ind["category"],
            "description": ind["description"],
        }
        for ind in _INDICATOR_DESCRIPTIONS
    ]
    
    countries_for_llm = [{"code": k, "name": v} for k, v in _COUNTRY_MAP.items()]
    
    import json
    prompt = _INDICATOR_SELECT_PROMPT.format(
        countries_json=json.dumps(countries_for_llm, ensure_ascii=False, indent=2),
        indicators_json=json.dumps(indicators_for_llm, ensure_ascii=False, indent=2),
        user_prompt=user_prompt,
    )
    
    result = await llm_client.ainvoke(prompt)
    content = result.content if hasattr(result, "content") else str(result)
    
    # 提取 JSON（处理 LLM 可能加了 Markdown 代码块的情况）
    import re
    json_match = re.search(r"\{[\s\S]*\}", content)
    if json_match:
        content = json_match.group(0)
    
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        # 降级方案：如果解析失败，默认返回 中国 + GDP + 人口
        return {
            "countries": [{"code": "CN", "name": "中国"}],
            "indicators": [
                {"code": "NY.GDP.MKTP.CD", "name": "GDP（现价美元）", "reason": "核心经济指标"},
                {"code": "SP.POP.TOTL", "name": "总人口", "reason": "基础人口指标"},
            ],
            "is_compare_mode": False,
            "explanation": "LLM 解析失败，使用默认配置（中国 GDP + 人口）",
        }
    
    # 向后兼容：处理旧格式（单个 country）
    if "country" in parsed and "countries" not in parsed:
        parsed["countries"] = [{"code": parsed["country"], "name": parsed.get("country_name", "未知国家")}]
        del parsed["country"]
        if "country_name" in parsed:
            del parsed["country_name"]
    
    # 确保 countries 字段存在
    if "countries" not in parsed or not parsed["countries"]:
        parsed["countries"] = [{"code": "CN", "name": "中国"}]
    
    # 限制数量
    if "indicators" in parsed and len(parsed["indicators"]) > max_indicators:
        parsed["indicators"] = parsed["indicators"][:max_indicators]
    if len(parsed["countries"]) > max_countries:
        parsed["countries"] = parsed["countries"][:max_countries]
    
    # 自动判断对比模式（多国家就是对比模式）
    parsed["is_compare_mode"] = parsed.get("is_compare_mode", len(parsed["countries"]) > 1)
    
    return parsed
