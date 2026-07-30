"""自动报告生成端到端管线。

一句话需求 → LLM 选指标 → 拉取数据 → 生成图表 → 生成报告。

使用方式：
    from service.report_pipeline import generate_report_from_prompt
    
    report_html = await generate_report_from_prompt(
        user_prompt="分析中国 GDP、人口和通胀趋势",
        llm_client=llm,
    )
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import List, Optional, Dict, Any

import pandas as pd

from service.viz_data.adapters.worldbank_adapter import (
    WorldBankAdapter,
    select_indicators_with_llm,
    _COUNTRY_MAP,
)
from service.viz_data.adapters.stats_gov_adapter import StatsGovAdapter
from service.viz_data.adapters.stats_gov_data import CHINA_MACRO_INDICATORS
from service.report_generator import generate_and_save_report


async def fetch_multiple_indicators(
    indicator_codes: List[str],
    country: str = "CN",
    start_year: int = 2010,
    end_year: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """并发拉取单个国家的多个指标数据。
    
    Args:
        indicator_codes: 指标代码列表
        country: 国家代码
        start_year: 起始年份
        end_year: 结束年份（默认当年）
    
    Returns:
        [
            {
                "indicator_code": "NY.GDP.MKTP.CD",
                "name": "GDP（现价美元）",
                "country_code": "CN",
                "country_name": "中国",
                "dataset": VizDataset,
                "df": pd.DataFrame,
            },
            ...
        ]
    """
    if end_year is None:
        end_year = pd.Timestamp.now().year
    
    from service.viz_data.adapters.worldbank_adapter import _COUNTRY_MAP
    country_name = _COUNTRY_MAP.get(country.upper(), country)
    
    # 并发创建 Adapter 并拉取
    async def _fetch_one(code: str):
        adapter = WorldBankAdapter(
            indicator=code,
            country=country,
            start_year=start_year,
            end_year=end_year,
        )
        dataset = await adapter.fetch()
        result = {
            "indicator_code": code,
            "name": dataset.name if dataset.name else code,
            "country_code": country.upper(),
            "country_name": country_name,
            "dataset": dataset,
            "df": None,
        }
        
        # 填充 DataFrame（从 parquet 读取）
        if dataset.tabular and dataset.tabular.data_ref:
            parquet_path = dataset.tabular.data_ref.path
            if parquet_path and Path(parquet_path).exists():
                result["df"] = pd.read_parquet(parquet_path)
        
        return result
    
    tasks = [_fetch_one(code) for code in indicator_codes]
    results = await asyncio.gather(*tasks)
    
    return [r for r in results if r.get("df") is not None]


async def fetch_multi_country_indicators(
    indicator_codes: List[str],
    country_codes: List[str],
    start_year: int = 2010,
    end_year: Optional[int] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """并发拉取多国家的多指标数据（对比模式）。
    
    Args:
        indicator_codes: 指标代码列表
        country_codes: 国家代码列表
        start_year: 起始年份
        end_year: 结束年份（默认当年）
    
    Returns:
        {
            "by_indicator": {
                "NY.GDP.MKTP.CD": [
                    {"country_code": "CN", "country_name": "中国", "df": pd.DataFrame, ...},
                    {"country_code": "US", "country_name": "美国", "df": pd.DataFrame, ...},
                ],
                ...
            },
            "all_data": [...],  # 平铺的所有数据
        }
    """
    # 并行拉取所有国家的所有指标
    all_tasks = []
    for country in country_codes:
        for indicator in indicator_codes:
            all_tasks.append((country, indicator))
    
    async def _fetch_one(country, indicator):
        results = await fetch_multiple_indicators(
            indicator_codes=[indicator],
            country=country,
            start_year=start_year,
            end_year=end_year,
        )
        return results[0] if results else None
    
    # 并发请求
    tasks = [_fetch_one(country, indicator) for country, indicator in all_tasks]
    all_results = await asyncio.gather(*tasks)
    all_results = [r for r in all_results if r is not None]
    
    # 按指标分组，方便生成对比图表
    by_indicator = {}
    for indicator in indicator_codes:
        by_indicator[indicator] = [r for r in all_results if r["indicator_code"] == indicator]
    
    return {
        "by_indicator": by_indicator,
        "all_data": all_results,
    }


def generate_charts_from_dataframes(
    data_list: List[Dict[str, Any]],
    chart_type: str = "line",
) -> List[str]:
    """从多个 DataFrame 生成 ECharts 图表 HTML（单国家模式）。
    
    Args:
        data_list: fetch_multiple_indicators 的结果
        chart_type: line（折线图）/ bar（柱状图）
    
    Returns:
        图表 HTML 字符串列表
    """
    try:
        from pyecharts.charts import Line, Bar
        from pyecharts import options as opts
        from pyecharts.globals import ThemeType
    except ImportError:
        # 如果没有 pyecharts，返回简单的占位 HTML
        return [
            f'<div style="height: 400px; background: #f8f9fa; display: flex; align-items: center; justify-content: center; border-radius: 8px; border: 2px dashed #ddd;"><b>图表 {i+1}：{data["name"]}</b></div>'
            for i, data in enumerate(data_list)
        ]
    
    charts_html = []
    
    for idx, data in enumerate(data_list):
        df = data.get("df")
        if df is None or df.empty:
            continue

        # 自动检测 X 轴列（优先 年份 -> 时间 -> 第一列）
        x_col = None
        for candidate in ["年份", "时间", "year", "date"]:
            if candidate in df.columns:
                x_col = candidate
                break
        if x_col is None:
            x_col = df.columns[0]

        # 按年份排序
        df = df.sort_values(x_col).reset_index(drop=True)

        # X 轴数据
        x_data = [str(y) for y in df[x_col].tolist()]

        # 自动检测 Y 轴数值列（优先 数值 -> 第一个数值类型列）
        y_col = None
        if "数值" in df.columns:
            y_col = "数值"
        else:
            # 找第一个数值类型列（排除 X 轴列和类别列）
            for col in df.columns:
                if col == x_col or col in ("季度", "月份"):
                    continue
                if df[col].dtype in ("int64", "float64", "int32", "float32"):
                    y_col = col
                    break
        if y_col is None:
            continue  # 没有数值列，跳过

        y_data = df[y_col].tolist()
        y_label = data["name"]
        
        # 自动单位缩放
        max_val = max(y_data) if y_data else 0
        unit = ""
        y_data_scaled = y_data
        if max_val >= 1e12:
            y_data_scaled = [v / 1e12 for v in y_data]
            unit = "（万亿美元）"
        elif max_val >= 1e8:
            y_data_scaled = [v / 1e8 for v in y_data]
            unit = "（亿人）"
        elif max_val >= 1e4:
            y_data_scaled = [v / 1e4 for v in y_data]
            unit = "（万）"
        
        # 生成图表
        if chart_type == "bar":
            chart = (
                Bar(init_opts=opts.InitOpts(theme=ThemeType.LIGHT, width="100%", height="400px"))
                .add_xaxis(xaxis_data=x_data)
                .add_yaxis(series_name=y_label, y_axis=y_data_scaled, label_opts=opts.LabelOpts(is_show=False))
                .set_global_opts(
                    title_opts=opts.TitleOpts(title=y_label),
                    tooltip_opts=opts.TooltipOpts(trigger="axis"),
                    yaxis_opts=opts.AxisOpts(name=unit),
                )
            )
        else:  # line
            chart = (
                Line(init_opts=opts.InitOpts(theme=ThemeType.LIGHT, width="100%", height="400px"))
                .add_xaxis(xaxis_data=x_data)
                .add_yaxis(series_name=y_label, y_axis=y_data_scaled, label_opts=opts.LabelOpts(is_show=False), is_smooth=True)
                .set_global_opts(
                    title_opts=opts.TitleOpts(title=y_label),
                    tooltip_opts=opts.TooltipOpts(trigger="axis"),
                    yaxis_opts=opts.AxisOpts(name=unit),
                )
            )
        
        charts_html.append(chart.render_embed())
    
    return charts_html


def generate_compare_charts(
    by_indicator: Dict[str, List[Dict[str, Any]]],
    chart_type: str = "line",
) -> List[str]:
    """生成多国家对比图表（对比模式）。
    
    每个指标一张图表，多个国家作为不同的系列。
    
    Args:
        by_indicator: fetch_multi_country_indicators["by_indicator"]
        chart_type: line / bar
    
    Returns:
        图表 HTML 字符串列表
    """
    try:
        from pyecharts.charts import Line, Bar
        from pyecharts import options as opts
        from pyecharts.globals import ThemeType
    except ImportError:
        return [
            f'<div style="height: 400px; background: #f8f9fa; display: flex; align-items: center; justify-content: center; border-radius: 8px; border: 2px dashed #ddd;"><b>对比图表：{list(by_indicator.keys())[i] if i < len(by_indicator) else "未知"}</b></div>'
            for i in range(len(by_indicator))
        ]
    
    # 国家颜色方案（最多 6 个国家）
    COLORS = ["#5470c6", "#91cc75", "#fac858", "#ee6666", "#73c0de", "#3ba272"]
    
    charts_html = []
    
    for indicator_idx, (indicator_code, country_data_list) in enumerate(by_indicator.items()):
        if not country_data_list:
            continue
        
        # 获取指标名称（用第一个国家的名称）
        indicator_name = country_data_list[0].get("name", indicator_code)
        
        # 找出所有出现过的年份（取所有国家年份的并集）
        all_years = set()
        for data in country_data_list:
            df = data.get("df")
            if df is not None and not df.empty:
                all_years.update(df["年份"].tolist())
        
        if not all_years:
            continue
        
        x_data = sorted([str(y) for y in all_years])
        
        # 计算所有国家该指标的最大值，用于统一单位缩放
        all_values = []
        for data in country_data_list:
            df = data.get("df")
            if df is not None and not df.empty:
                all_values.extend(df["数值"].tolist())
        
        max_val = max(all_values) if all_values else 0
        unit = ""
        scale_factor = 1
        if max_val >= 1e12:
            scale_factor = 1e12
            unit = "（万亿美元）"
        elif max_val >= 1e8:
            scale_factor = 1e8
            unit = "（亿人）"
        elif max_val >= 1e4:
            scale_factor = 1e4
            unit = "（万）"
        
        # 初始化图表
        if chart_type == "bar":
            chart = Bar(init_opts=opts.InitOpts(theme=ThemeType.LIGHT, width="100%", height="450px"))
        else:
            chart = Line(init_opts=opts.InitOpts(theme=ThemeType.LIGHT, width="100%", height="450px"))
        
        chart.add_xaxis(xaxis_data=x_data)
        
        # 为每个国家添加一个系列
        for country_idx, data in enumerate(country_data_list):
            df = data.get("df")
            if df is None or df.empty:
                continue
            
            country_name = data.get("country_name", data.get("country_code", "未知国家"))
            
            # 按年份对齐数据（填充缺失年份为 None）
            year_to_value = dict(zip(df["年份"].tolist(), df["数值"].tolist()))
            y_data = [year_to_value.get(int(year)) for year in x_data]
            
            # 应用缩放
            y_data_scaled = [v / scale_factor if v is not None else None for v in y_data]
            
            # 添加系列
            color = COLORS[country_idx % len(COLORS)]
            if chart_type == "line":
                chart.add_yaxis(
                    series_name=country_name,
                    y_axis=y_data_scaled,
                    label_opts=opts.LabelOpts(is_show=False),
                    is_smooth=True,
                    color=color,
                )
            else:
                chart.add_yaxis(
                    series_name=country_name,
                    y_axis=y_data_scaled,
                    label_opts=opts.LabelOpts(is_show=False),
                    color=color,
                )
        
        # 全局配置
        chart.set_global_opts(
            title_opts=opts.TitleOpts(title=f"{indicator_name}（对比）"),
            tooltip_opts=opts.TooltipOpts(trigger="axis"),
            legend_opts=opts.LegendOpts(orient="horizontal", top="5%"),
            yaxis_opts=opts.AxisOpts(name=unit),
            datazoom_opts=[opts.DataZoomOpts()],  # 添加数据缩放条
        )
        
        charts_html.append(chart.render_embed())
    
    return charts_html


async def _generate_china_macro_report(
    user_prompt: str,
    llm_client,
    output_path: Optional[str] = None,
    start_year: int = 2020,
    end_year: Optional[int] = None,
) -> Dict[str, Any]:
    """生成中国宏观经济分析报告（国家统计局数据）。"""
    # Step 1: LLM 选择指标
    indicators = await select_china_macro_indicators(user_prompt, llm_client)
    if not indicators:
        return {"success": False, "error": "未选择到合适的指标"}

    indicator_codes = [ind["code"] for ind in indicators]

    # Step 2: 并发拉取数据
    data_list = await fetch_china_macro_indicators(
        indicator_codes=indicator_codes,
        start_year=start_year,
        end_year=end_year,
    )

    datasets = [d["dataset"] for d in data_list if d.get("dataset")]

    if not datasets:
        return {"success": False, "error": "未获取到有效数据"}

    # Step 3: 生成图表（直接用 df 渲染）
    charts = generate_charts_from_dataframes(data_list)

    # Step 4: 确定输出路径
    if output_path is None:
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = Path("charts")
        output_dir.mkdir(exist_ok=True)
        output_path = str(output_dir / f"report_china_{timestamp}.html")

    # Step 5: 生成完整报告
    report_path = await generate_and_save_report(
        output_path=output_path,
        title="中国宏观经济分析报告",
        datasets=datasets,
        charts=charts,
        user_prompt=user_prompt,
        llm_client=llm_client,
    )

    report_html = Path(report_path).read_text(encoding="utf-8")

    return {
        "success": True,
        "data_source": "国家统计局",
        "report_html": report_html,
        "report_path": str(report_path),
        "selected_indicators": indicators,
        "datasets": datasets,
        "charts": charts,
    }


async def generate_report_from_prompt(
    user_prompt: str,
    llm_client,
    output_path: Optional[str] = None,
    start_year: int = None,
    end_year: Optional[int] = None,
) -> Dict[str, Any]:
    """一句话生成完整的分析报告（端到端，支持多国家对比）。
    
    流程：
        1. LLM 根据用户需求自动选择国家和指标（支持对比模式）
        2. 并发拉取所有国家的所有指标数据
        3. 智能对齐年份，生成对比图表（多系列折线图）
        4. LLM 写分析文字，拼接成完整 HTML 报告
    
    Args:
        user_prompt: 用户需求（如 "分析中国 GDP" / "对比中美 GDP 和人口"）
        llm_client: LLM 客户端（需支持 ainvoke）
        output_path: 报告输出路径（可选，默认 charts/ 目录）
        start_year: 数据起始年份
        end_year: 数据结束年份（默认当年）
    
    Returns:
        {
            "success": bool,
            "is_compare_mode": bool,
            "report_html": str,
            "report_path": str,
            "countries": list,
            "selected_indicators": list,
            "datasets": list[VizDataset],
            "charts": list[str],
        }
    """
    try:
        # Step 0: LLM 自动选择数据源
        data_source = await select_data_source_with_llm(user_prompt, llm_client)

        # 国家统计局分支（中国国内宏观分析）
        if data_source == "stats_gov" or data_source == "both":
            if start_year is None:
                start_year = 2020  # 国内数据默认从2020年开始
            result = await _generate_china_macro_report(
                user_prompt=user_prompt,
                llm_client=llm_client,
                output_path=output_path,
                start_year=start_year,
                end_year=end_year,
            )
            if result["success"] or data_source == "stats_gov":
                # 如果是纯 stats_gov，或 both 且成功了，直接返回
                return result

        # 世界银行分支（跨国对比 / 国际视角）
        if start_year is None:
            start_year = 2010  # 世界银行数据默认从2010年开始

        # Step 1: LLM 选择国家和指标（支持对比模式）
        selection = await select_indicators_with_llm(user_prompt, llm_client)
        countries = selection.get("countries", [{"code": "CN", "name": "中国"}])
        indicators = selection.get("indicators", [])
        is_compare_mode = selection.get("is_compare_mode", len(countries) > 1)
        
        if not indicators:
            return {
                "success": False,
                "error": "未选择到合适的指标",
            }
        
        indicator_codes = [ind["code"] for ind in indicators]
        country_codes = [c["code"] for c in countries]
        country_names = [c["name"] for c in countries]
        
        # Step 2: 拉取数据
        datasets = []
        charts = []
        
        if is_compare_mode:
            # 对比模式：多国家 + 多指标
            multi_data = await fetch_multi_country_indicators(
                indicator_codes=indicator_codes,
                country_codes=country_codes,
                start_year=start_year,
                end_year=end_year,
            )
            
            # 收集所有 dataset
            for data in multi_data["all_data"]:
                if data.get("dataset"):
                    datasets.append(data["dataset"])
            
            # 生成对比图表
            charts = generate_compare_charts(multi_data["by_indicator"])
            
            # 报告标题
            title_countries = " vs ".join(country_names[:3])
            report_title = f"{title_countries}宏观经济对比分析报告"
        else:
            # 单国家模式
            country = country_codes[0]
            country_name = country_names[0]
            
            data_list = await fetch_multiple_indicators(
                indicator_codes=indicator_codes,
                country=country,
                start_year=start_year,
                end_year=end_year,
            )
            
            datasets = [d["dataset"] for d in data_list if d.get("dataset")]
            charts = generate_charts_from_dataframes(data_list)
            
            # 报告标题
            report_title = f"{country_name}宏观经济分析报告"
            if "GDP" in user_prompt or "gdp" in user_prompt:
                report_title = f"{country_name} GDP 趋势分析报告"
            elif "人口" in user_prompt:
                report_title = f"{country_name}人口数据分析报告"
        
        if not datasets:
            return {
                "success": False,
                "error": "未获取到有效数据",
                "selected_indicators": indicators,
                "countries": countries,
            }
        
        # Step 3: 确定输出路径
        if output_path is None:
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_dir = Path("charts")
            output_dir.mkdir(exist_ok=True)
            output_path = str(output_dir / f"report_{timestamp}.html")
        
        # Step 4: 生成完整报告
        report_path = await generate_and_save_report(
            output_path=output_path,
            title=report_title,
            datasets=datasets,
            charts=charts,
            user_prompt=user_prompt,
            llm_client=llm_client,
        )
        
        # 读取报告 HTML
        report_html = Path(report_path).read_text(encoding="utf-8")
        
        return {
            "success": True,
            "is_compare_mode": is_compare_mode,
            "report_html": report_html,
            "report_path": str(report_path),
            "countries": countries,
            "selected_indicators": indicators,
            "datasets": datasets,
            "charts": charts,
            "selection_explanation": selection.get("explanation", ""),
        }
    
    except Exception as e:
        import traceback
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }


# 便捷函数：带默认 LLM 初始化
def get_default_llm():
    """获取默认 LLM 客户端（从项目配置加载）。
    
    这个函数会自动适配项目中已有的 LLM 配置方式。
    """
    try:
        # 尝试加载项目的 LLM 配置
        from agent.config import load_agent_config
        from langchain_openai import ChatOpenAI
        
        config = load_agent_config()
        base_url = config.get("base_url", "http://localhost:11434/v1")
        api_key = config.get("api_key", "ollama")
        model = config.get("model", "qwen2.5:7b")
        
        return ChatOpenAI(
            base_url=base_url,
            api_key=api_key,
            model=model,
            temperature=0,
        )
    except Exception as e:
        # 如果配置加载失败，返回 None（会用降级文案）
        print(f"LLM 配置加载失败：{e}，将使用静态文案")
        return None


# ============================================================
# LLM 数据源智能选择（世界银行 vs 国家统计局）
# ============================================================

_DATA_SOURCE_SELECT_PROMPT = """
你是一位数据专家，请根据用户需求选择最合适的数据源。

可用数据源：
1. world_bank（世界银行）：
   - 支持跨国对比（中国、美国、日本、德国等20+国家）
   - 指标：GDP、人口、CPI、失业率、进出口等
   - 适合：跨国对比、国际视角

2. stats_gov（国家统计局）：
   - 仅限中国国内数据
   - 指标：GDP季度、CPI月度、工业增加值、社零总额、城镇失业率
   - 数据频率更高（月度/季度）、更新到2024年
   - 适合：中国国内经济分析、行业景气度

用户需求：{user_prompt}

返回严格JSON格式：
{{
    "source": "world_bank" 或 "stats_gov" 或 "both",
    "reason": "选择理由",
    "suggestions": "用户建议（如需求不明确）"
}}
"""


async def select_data_source_with_llm(user_prompt: str, llm_client) -> str:
    """LLM 智能选择数据源。
    
    Returns:
        "world_bank" / "stats_gov" / "both"
    """
    if not llm_client:
        # 默认用国家统计局数据（因为更贴近国内用户需求）
        return "stats_gov"

    import json
    import re

    prompt = _DATA_SOURCE_SELECT_PROMPT.format(user_prompt=user_prompt)
    result = await llm_client.ainvoke(prompt)
    content = result.content if hasattr(result, "content") else str(result)

    # 提取 JSON
    json_match = re.search(r"\{[\s\S]*\}", content)
    if json_match:
        content = json_match.group(0)

    try:
        parsed = json.loads(content)
        return parsed.get("source", "stats_gov")
    except json.JSONDecodeError:
        return "stats_gov"


# ============================================================
# 中国宏观数据（国家统计局）并发获取
# ============================================================

async def fetch_china_macro_indicators(
    indicator_codes: List[str],
    start_year: int = 2020,
    end_year: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """并发获取中国宏观经济指标数据。
    
    Args:
        indicator_codes: 指标代码列表
        start_year: 起始年份
        end_year: 结束年份（默认当年）
    
    Returns:
        每个指标的数据，含 df, dataset 等字段
    """
    async def _fetch_one(code: str):
        adapter = StatsGovAdapter(
            indicator_code=code,
            start_year=start_year,
            end_year=end_year,
        )
        dataset = await adapter.fetch()
        # 从 parquet 读取 df
        df = None
        if dataset.tabular and dataset.tabular.data_ref:
            import pandas as pd
            df = pd.read_parquet(dataset.tabular.data_ref.path)
        return {
            "indicator_code": code,
            "name": dataset.name,
            "dataset": dataset,
            "df": df,
        }

    tasks = [_fetch_one(code) for code in indicator_codes]
    results = await asyncio.gather(*tasks)
    return [r for r in results if r.get("df") is not None]


# ============================================================
# 中国宏观指标选择 Prompt
# ============================================================

_CHINA_INDICATOR_SELECT_PROMPT = """
你是一位中国宏观经济分析师，请根据用户需求选择最合适的指标（最多选3个）。

可用指标列表：
{indicators_json}

用户需求：{user_prompt}

返回严格JSON格式：
{{
    "indicators": [
        {{
            "code": "指标代码",
            "name": "指标名称",
            "reason": "选择理由"
        }}
    ],
    "explanation": "一句话说明选择思路"
}}
"""


async def select_china_macro_indicators(
    user_prompt: str,
    llm_client,
    max_indicators: int = 3,
) -> List[Dict[str, Any]]:
    """为中国宏观数据分析选择指标。"""
    if not llm_client:
        # 降级默认选 GDP + CPI + 工业增加值
        return [
            {"code": "GDP_QUARTERLY", "name": "GDP（季度）", "reason": "核心经济增长指标"},
            {"code": "CPI_MONTHLY", "name": "CPI居民消费价格指数", "reason": "价格通胀指标"},
            {"code": "INDUSTRIAL_VALUE_ADDED", "name": "规模以上工业增加值", "reason": "工业生产景气度"},
        ]

    import json
    import re

    indicators_for_llm = [
        {
            "code": ind["code"],
            "name": ind["name"],
            "category": ind["category"],
            "description": ind["description"],
        }
        for ind in CHINA_MACRO_INDICATORS
    ]

    prompt = _CHINA_INDICATOR_SELECT_PROMPT.format(
        indicators_json=json.dumps(indicators_for_llm, ensure_ascii=False, indent=2),
        user_prompt=user_prompt,
    )

    result = await llm_client.ainvoke(prompt)
    content = result.content if hasattr(result, "content") else str(result)

    json_match = re.search(r"\{[\s\S]*\}", content)
    if json_match:
        content = json_match.group(0)

    try:
        parsed = json.loads(content)
        indicators = parsed.get("indicators", [])
        if len(indicators) > max_indicators:
            indicators = indicators[:max_indicators]
        return indicators
    except json.JSONDecodeError:
        # 降级默认选 3 个
        return [
            {"code": "GDP_QUARTERLY", "name": "GDP（季度）"},
            {"code": "CPI_MONTHLY", "name": "CPI居民消费价格指数"},
            {"code": "INDUSTRIAL_VALUE_ADDED", "name": "规模以上工业增加值"},
        ]
