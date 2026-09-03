"""数据接入层的核心数据模型。

DataProfile 替代旧的 VizDataset/TabularBlock/ColumnSchema/SemanticHints。
设计原则: 薄中间层 -- 只提供 LLM 写图表代码所需的最少信息。
v4: 不再物化 DuckDB，数据以语义 Series 存储；DataProfile 附挂 series_catalog。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from service.data_ingestion.series.models import SemanticSeries, SeriesCatalog


@dataclass
class RawTable:
    """一个 reader 产出的原始 DataFrame（尚未拆分 series）。

    多 sheet Excel / 多表数据库 / 多文件源会产出多个 RawTable。
    """

    name: str                                 # 逻辑表名（来自文件名 / sheet 名 / 查询名）
    df: Any                                   # pandas.DataFrame（避免运行时强依赖 pandas 类型注解）
    source_kind: str                          # "file" | "database" | "api" | "document" | "archive"
    source_path: str                          # 原始数据源路径/连接串
    degraded: bool = False                    # ★ 解析降级标记（router 失败回退时置 True）
    degraded_reason: str = ""                 # ★ 降级原因（如 llm_tabular_failed: ...）


def safe_table_name(name: str | None, fallback: str = "data") -> str:
    """把文件名/用户名转换为合法的逻辑表名（取自旧 DuckDBManager.safe_table_name）。"""
    from pathlib import Path

    if not name:
        return fallback
    # 取文件名 (去扩展名) 或直接用 name
    base = Path(name).stem if "." in name else name
    # 只保留字母数字下划线
    safe = "".join(c if c.isalnum() or c == "_" else "_" for c in base)
    safe = safe.strip("_") or fallback
    # 避免数字开头
    if safe[0].isdigit():
        safe = f"t_{safe}"
    return safe.lower()


@dataclass
class DataSource:
    """用户提供的数据源描述。router 根据此信息路由到对应 reader。"""

    kind: Literal["file", "database", "api", "archive", "document"]
    path: str | None = None          # 文件路径 / 连接串 / API URL
    name: str | None = None          # 用户可读名称 (可选, 用于生成表名)
    # database 专用
    db_type: Literal["postgresql", "mysql", "sqlite"] | None = None
    db_config: dict[str, Any] | None = None  # 连接参数
    # api 专用
    api_params: dict[str, Any] | None = None  # API 查询参数
    # 通用
    options: dict[str, Any] = field(default_factory=dict)  # reader 特定选项


@dataclass
class DataProfile:
    """数据画像 -- 替代 VizDataset 的轻量契约。

    所有 reader 产出此对象。chart_generator 消费它来选择语义 series 并生成 pyecharts 代码。
    table_name 指原始来源表名（溯源用途），实际数据存于 series_catalog 的各 SemanticSeries。
    """

    table_name: str                           # 原始数据源表名（溯源）
    source_kind: str                          # "file" | "database" | "api" | "document"
    source_path: str                          # 原始数据源路径/连接串
    schema: list[dict[str, str]]              # [{"name": "col1", "type": "VARCHAR"}, ...]
    row_count: int
    preview: list[dict[str, Any]]             # 前 N 行, JSON 可序列化
    stats: dict[str, dict[str, Any]]          # {"col1": {"min":.., "max":.., "mean":..}, ...}
    session_dir: str = ""                     # 会话目录（内含 manifest.json + 各 series .parquet）
    series_catalog: "SeriesCatalog | None" = None   # 本会话的语义 series 目录
    related_tables: list["DataProfile"] = field(default_factory=list)  # 多表场景 (如多 sheet Excel)
    column_semantics: dict[str, str] = field(default_factory=dict)   # 列名 -> semantic_role (time/measure/dimension/id)
    detected_patterns: list[str] = field(default_factory=list)       # time_series / categorical_comparison
    degraded: bool = False                                     # ★ 主表降级标记
    degraded_reason: str = ""                                  # ★ 降级原因

    def runs_series(self, series_id: str) -> "SemanticSeries | None":
        """按 series_id 从本会话目录解析语义 series；无目录时返回 None。"""
        if self.series_catalog is None:
            return None
        return self.series_catalog.by_id(series_id)

    def to_prompt_dict(self) -> dict:
        """生成给 LLM prompt 用的精简 dict (去掉内部路径等敏感信息)。

        schema 每列附 semantic_role；顶层 semantic_hints.detected_patterns
        供 designer prompt 做图表类型推荐。附 series 索引。
        """
        schema_with_role = []
        for col in self.schema:
            c = dict(col)
            if col["name"] in self.column_semantics:
                c["semantic_role"] = self.column_semantics[col["name"]]
            schema_with_role.append(c)
        return {
            "table_name": self.table_name,
            "source_kind": self.source_kind,
            "schema": schema_with_role,
            "row_count": self.row_count,
            "preview": self.preview,
            "stats": self.stats,
            "semantic_hints": {"detected_patterns": self.detected_patterns},
            "series_index": (
                self.series_catalog.to_index_prompt() if self.series_catalog else "(未提供)"
            ),
            "related_tables": [
                {"table_name": t.table_name, "schema": t.schema, "row_count": t.row_count}
                for t in self.related_tables
            ],
        }

    def to_prompt_str(self) -> str:
        """生成给 LLM prompt 用的可读字符串。"""
        import json

        lines = [
            f"数据源类型: {self.source_kind}",
            f"数据表名: {self.table_name}",
            f"行数: {self.row_count}",
            "",
            "Schema:",
        ]
        for col in self.schema:
            lines.append(f"  - {col['name']}: {col['type']}")

        lines.append("")
        lines.append("Preview (前 10 行):")
        lines.append(json.dumps(self.preview, ensure_ascii=False, indent=2, default=str))

        if self.series_catalog is not None and self.series_catalog.series:
            lines.append("")
            lines.append("可用数据系列 (series):")
            lines.append(self.series_catalog.to_index_prompt())

        if self.stats:
            lines.append("")
            lines.append("Stats:")
            lines.append(json.dumps(self.stats, ensure_ascii=False, indent=2, default=str))

        if self.related_tables:
            lines.append("")
            lines.append(f"关联表 ({len(self.related_tables)} 个):")
            for t in self.related_tables:
                cols = ", ".join(f"{c['name']}:{c['type']}" for c in t.schema)
                lines.append(f"  - {t.table_name} ({t.row_count} 行): {cols}")

        return "\n".join(lines)
