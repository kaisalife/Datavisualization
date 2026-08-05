"""API 数据源 Reader。

从 HTTP API (WorldBank/StatsGov 等) 拉取数据，
转为 DataFrame 后注册到 DuckDB。

支持两种模式:
1. 内置 API: WorldBank / StatsGov (预设 URL 和解析逻辑)
2. 通用 API: 用户提供 URL + JSON path
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

import pandas as pd

from service.data_ingestion.duckdb_manager import DuckDBManager
from service.data_ingestion.models import DataProfile
from service.data_ingestion.profiler import build_profile


def _fetch_json(url: str, headers: dict | None = None, timeout: int = 30) -> Any:
    """简单的 HTTP GET 获取 JSON。"""
    req = Request(url, headers=headers or {"Accept": "application/json"})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ------------------------------------------------------------------
# 内置 API 数据源
# ------------------------------------------------------------------

def _fetch_worldbank(
    indicator: str,
    countries: str = "all",
    date_range: str = "2010:2024",
) -> pd.DataFrame:
    """从 World Bank API 获取指标数据。

    Args:
        indicator: 世界银行指标代码, 如 "NY.GDP.MKTP.CD" (GDP)
        countries: 国家代码, "all" 或 "CHN;USA;JPN"
        date_range: "2010:2024"
    """
    url = (
        f"https://api.worldbank.org/v2/country/{countries}/indicator/{indicator}"
        f"?date={date_range}&format=json&per_page=10000"
    )
    data = _fetch_json(url)
    # WorldBank 返回 [meta, records]
    if isinstance(data, list) and len(data) >= 2:
        records = data[1]
    elif isinstance(data, list):
        records = data
    else:
        records = data

    if not records:
        raise ValueError(f"WorldBank API 返回空数据: {url}")

    df = pd.DataFrame(records)
    # 展开嵌套的 country 字段
    if "country" in df.columns:
        df["country"] = df["country"].apply(
            lambda x: x.get("value", str(x)) if isinstance(x, dict) else str(x)
        )
    if "indicator" in df.columns:
        df["indicator"] = df["indicator"].apply(
            lambda x: x.get("value", str(x)) if isinstance(x, dict) else str(x)
        )
    return df


def _fetch_statsgov(
    indicator: str,
    frequency: str = "yearly",
) -> pd.DataFrame:
    """从国家统计局 API 获取数据。

    使用内置统计数据作为 fallback。
    """
    from service.data_ingestion.builtin_data.stats_gov_data import get_indicator_data

    data = get_indicator_data(indicator)
    if not data:
        raise ValueError(f"未知的统计指标: {indicator}")

    df = pd.DataFrame(data)
    return df


# ------------------------------------------------------------------
# 通用 API Reader
# ------------------------------------------------------------------

class ApiReader:
    """从 API 获取数据并注册为 DuckDB 表。"""

    # 内置 API 映射
    BUILTIN_APIS = {
        "worldbank": _fetch_worldbank,
        "statsgov": _fetch_statsgov,
    }

    @staticmethod
    def can_handle(source_kind: str) -> bool:
        return source_kind == "api"

    @staticmethod
    def read(
        db: DuckDBManager,
        api_type: str | None = None,
        url: str | None = None,
        params: dict[str, Any] | None = None,
        table_name: str | None = None,
    ) -> DataProfile:
        """从 API 获取数据并注册为 DuckDB 表。

        Args:
            db: DuckDBManager 实例
            api_type: 内置 API 类型 ("worldbank" / "statsgov")
            url: 通用 API URL (api_type 为 None 时使用)
            params: API 查询参数
            table_name: 目标表名

        Returns:
            DataProfile
        """
        params = params or {}

        if api_type and api_type.lower() in ApiReader.BUILTIN_APIS:
            # 内置 API
            fetcher = ApiReader.BUILTIN_APIS[api_type.lower()]
            df = fetcher(**params)
            source_path = f"api://{api_type}"
        elif url:
            # 通用 API
            data = _fetch_json(url)
            # 尝试解析 JSON 为 DataFrame
            if isinstance(data, list):
                df = pd.DataFrame(data)
            elif isinstance(data, dict):
                # 尝试找到数据数组
                for key in ["data", "results", "items", "records"]:
                    if key in data and isinstance(data[key], list):
                        df = pd.DataFrame(data[key])
                        break
                else:
                    df = pd.DataFrame([data])
            else:
                df = pd.DataFrame([{"value": data}])
            source_path = url
        else:
            raise ValueError("必须提供 api_type 或 url")

        name = table_name or DuckDBManager.safe_table_name(
            api_type or params.get("indicator") or "api_data"
        )
        db.register_dataframe(name, df)
        return build_profile(db, name, source_kind="api", source_path=source_path)
