"""图表计划 Pydantic 模型（v4 数据契约）。

LLM 输出的图表计划必须有强类型 schema，避免字段拼错、缺失字段、值类型不一致
导致的运行时炸。本文件定义单条 plan 与 plans bundle 的 schema。

字段名兼容 LLM 常见命名差异：plan_id / planName / id 都接受。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ChartType = Literal[
    "Line", "Bar", "Scatter", "Pie", "Area", "Histogram",
    "Boxplot", "Heatmap", "Candlestick", "Radar", "Funnel",
    "Gauge", "Treemap", "WordCloud", "Graph", "Parallel",
    "Sankey", "ThemeRiver",
]


class ChartPlan(BaseModel):
    """单个图表计划。

    series_id 必须指向 service.data_ingestion.series.SeriesCatalog 中的某条 series。
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    plan_id: str = Field(..., description="唯一 ID，同一 task 内不可重复")
    plan_name: str = Field("", description="人类可读名")
    chart_type: ChartType = Field("Bar", description="pyecharts 图表类型")
    chart_title: str = Field("", description="图表标题")
    chart_reason: str = Field("", description="选择该图表的原因说明")
    series_id: str = Field(..., description="★ 数据契约 v4：引用 SeriesCatalog 中的 series")
    transform_hint: str = Field("", description="数据变换提示，注入 sandbox 代码注释")
    x_axis: str | None = Field(None, description="x 轴列名")
    y_axis: list[str] | None = Field(None, description="y 轴列名列表")
    use_column_names: list[str] | None = Field(None, description="实际使用的列名")
    data_interface: str = Field("", description="（可选）数据接口代码片段")
    execution_order: int = Field(0, description="执行顺序")
    layout: dict | None = Field(None, description="布局配置（col/row 等）")

    @field_validator("series_id")
    @classmethod
    def series_id_must_be_nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("series_id 不能为空（数据契约 v4）")
        return v


class PlanBundle(BaseModel):
    """LLM 返回的 plans 容器。"""

    model_config = ConfigDict(extra="ignore")

    plans: list[ChartPlan] = Field(default_factory=list)


def coerce_plan_dict(raw: dict) -> dict:
    """兼容 LLM 输出的多种命名（snake / camel）。

    例如 LLM 可能输出 planId / chartTitle / seriesId 等驼峰形式。
    """
    if not isinstance(raw, dict):
        return raw

    aliases = {
        "planId": "plan_id",
        "planName": "plan_name",
        "chartType": "chart_type",
        "chartTitle": "chart_title",
        "chartReason": "chart_reason",
        "seriesId": "series_id",
        "transformHint": "transform_hint",
        "xAxis": "x_axis",
        "yAxis": "y_axis",
        "useColumnNames": "use_column_names",
        "dataInterface": "data_interface",
        "executionOrder": "execution_order",
    }
    out = dict(raw)
    for k_src, k_dst in aliases.items():
        if k_src in out and k_dst not in out:
            out[k_dst] = out.pop(k_src)
    return out


def parse_plans(raw: dict | list) -> list[ChartPlan]:
    """把 LLM 原始输出解析为强类型 plans 列表。

    接受以下格式：
    - {"plans": [...]}  - {"plans": [{"plan_id": ..., ...}, ...]}
    - [...]             - 直接的 plans 数组
    """
    if isinstance(raw, list):
        data = {"plans": raw}
    elif isinstance(raw, dict):
        data = raw if "plans" in raw and isinstance(raw["plans"], list) else {"plans": [raw]}
    else:
        raise ValueError(f"plans 必须是 dict 或 list，实际: {type(raw).__name__}")

    normalized = {
        "plans": [coerce_plan_dict(p) for p in data["plans"]],
    }
    bundle = PlanBundle.model_validate(normalized)
    return bundle.plans


def plan_get(plan, key: str, default=None):
    """统一 plan 字段读取：同时支持 ChartPlan 与 dict（兼容历史调用方）。

    下游模块（chart_executor / chart_generator / plan_validator 等）大量使用
    ``plan.get("field", default)`` 模式，本函数保留该用法，同时让 ChartPlan 也能通过。
    """
    if isinstance(plan, ChartPlan):
        return getattr(plan, key, default)
    if isinstance(plan, dict):
        return plan.get(key, default)
    return default


def plan_field(plan, key: str, default=None):
    """plan_get 的别名，调用方按风格选用。"""
    return plan_get(plan, key, default)
