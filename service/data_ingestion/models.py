"""数据接入层的核心数据模型。

DataProfile 替代旧的 VizDataset/TabularBlock/ColumnSchema/SemanticHints。
设计原则: 薄中间层 -- 只提供 LLM 写图表代码所需的最少信息。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


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

    所有 reader 产出此对象。chart_generator 消费它来生成 SQL + pyecharts 代码。
    """

    table_name: str                           # DuckDB 中注册的表名/视图名
    source_kind: str                          # "file" | "database" | "api" | "document"
    source_path: str                          # 原始数据源路径/连接串
    schema: list[dict[str, str]]              # [{"name": "col1", "type": "VARCHAR"}, ...]
    row_count: int
    preview: list[dict[str, Any]]             # 前 N 行, JSON 可序列化
    stats: dict[str, dict[str, Any]]          # {"col1": {"min":.., "max":.., "mean":..}, ...}
    duckdb_path: str                          # .duckdb 文件路径 (沙箱进程通过此路径连接)
    parquet_path: str | None = None           # 标准化 parquet 落盘路径 (如果有)
    related_tables: list["DataProfile"] = field(default_factory=list)  # 多表场景 (如多 sheet Excel)
    column_semantics: dict[str, str] = field(default_factory=dict)   # 列名 -> semantic_role (time/measure/dimension/id)
    detected_patterns: list[str] = field(default_factory=list)       # time_series / categorical_comparison

    def to_prompt_dict(self) -> dict:
        """生成给 LLM prompt 用的精简 dict (去掉内部路径等敏感信息)。

        schema 每列附 semantic_role；顶层 semantic_hints.detected_patterns
        供 designer prompt 做图表类型推荐。
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
            f"DuckDB 表名: {self.table_name}",
            f"行数: {self.row_count}",
            "",
            "Schema:",
        ]
        for col in self.schema:
            lines.append(f"  - {col['name']}: {col['type']}")

        lines.append("")
        lines.append("Preview (前 10 行):")
        lines.append(json.dumps(self.preview, ensure_ascii=False, indent=2, default=str))

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
