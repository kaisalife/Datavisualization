"""国家统计局宏观数据 Adapter。

使用内置预置数据（2013-2024），零外部依赖，零合规风险。

涵盖指标：
- GDP（季度）：累计值、同比增长率
- CPI（月度）：同比、环比
- 规模以上工业增加值（月度）：同比增长率
- 社会消费品零售总额（月度）：同比增长率
- 城镇调查失业率（月度）
"""
from __future__ import annotations

import pandas as pd

from service.viz_data.adapters.base import VizDataAdapter
from service.viz_data.adapters.stats_gov_data import (
    CHINA_MACRO_INDICATORS,
    get_indicator_data,
)
from service.viz_data.capabilities import AdapterCapabilities
from service.viz_data.schema import DataRef, TabularBlock, VizDataset
from service.viz_data.storage import new_dataset_dir, save_dataframe_to_parquet


class StatsGovAdapter(VizDataAdapter):
    """国家统计局宏观数据适配器。"""

    def __init__(self, indicator_code: str, start_year: int = None, end_year: int = None):
        """
        Args:
            indicator_code: 指标代码（见 CHINA_MACRO_INDICATORS）
            start_year: 起始年份（默认不限制）
            end_year: 结束年份（默认不限制）
        """
        self.indicator_code = indicator_code
        self.start_year = start_year
        self.end_year = end_year

    def source_kind(self) -> str:
        return "china_macro"

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(needs_llm=False, supports_multi_query=True)

    async def fetch(self, engine=None) -> VizDataset:
        """获取数据并组装成 VizDataset。"""
        raw_data = get_indicator_data(self.indicator_code)
        if not raw_data:
            raise ValueError(f"指标代码不存在: {self.indicator_code}")

        # 转换为 DataFrame
        df = pd.DataFrame(raw_data)

        # 年份过滤
        if self.start_year:
            df = df[df["年份"] >= self.start_year]
        if self.end_year:
            df = df[df["年份"] <= self.end_year]

        # 添加时间列用于排序和显示
        if "季度" in df.columns:
            df["时间"] = df.apply(lambda row: f"{int(row['年份'])}Q{int(row['季度'])}", axis=1)
        elif "月份" in df.columns:
            df["时间"] = df.apply(
                lambda row: f"{int(row['年份'])}-{int(row['月份']):02d}", axis=1
            )

        # 落盘
        dataset_dir = new_dataset_dir()
        if isinstance(dataset_dir, tuple):
            dataset_dir = dataset_dir[1]
        parquet_path = save_dataframe_to_parquet(df, dataset_dir, self.indicator_code)

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

        # 查找指标元信息
        indicator_info = None
        for info in CHINA_MACRO_INDICATORS:
            if info["code"] == self.indicator_code:
                indicator_info = info
                break

        indicator_name = indicator_info["name"] if indicator_info else self.indicator_code
        description = indicator_info["description"] if indicator_info else ""

        return VizDataset(
            dataset_id=f"stats_gov_{self.indicator_code}",
            name=indicator_name,
            source_kind="china_macro",
            tabular=tabular,
            descriptor=type(
                "obj",
                (object,),
                {
                    "kind": "china_macro",
                    "label": f"国家统计局: {indicator_name}",
                    "logical_id": f"stats_gov_{self.indicator_code}",
                    "extra": {
                        "source": "国家统计局",
                        "indicator_code": self.indicator_code,
                        "indicator_name": indicator_name,
                        "description": description,
                        "category": indicator_info["category"] if indicator_info else "",
                        "rows": len(df),
                    },
                },
            )(),
        )

    @staticmethod
    def get_available_indicators() -> list:
        """获取所有可用指标列表（供 LLM 选择）。"""
        return CHINA_MACRO_INDICATORS

    def normalize(self, raw):
        """Phase 2: fetch 已完成全部工作，normalize 直接返回。"""
        return raw


# 从 df_stats 导入（放在末尾避免循环导入）
from service.introspection.df_stats import dataframe_to_column_schemas
