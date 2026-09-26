"""Series 数据模型（v4）。

SemanticSeries: 一个"面向可视化"的语义化数据切片，携带行标签、列标签与具体含义。
SeriesCatalog:  一数据会话（一个会话目录）下全部 series 的目录，负责 manifest 序列化与索引输出。
纯数据结构，不含 IO 与代码生成逻辑。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SemanticSeries:
    """一条语义化 series（可视化直接可用的数据切片）。

    series_id 形如 "源名.系列名"（如 "年度数据.城镇居民人均可支配收入"），
    是 plan -> 生成阶段的引用主键。
    """

    series_id: str
    name: str                              # 语义含义（"城镇居民人均可支配收入 年度趋势"）
    axis_kind: str                          # time_series / categorical_comparison / distribution / part_to_whole / generic
    row_label_column: str | None            # 行/x 轴标签所在的列名（时间点或类别）
    column_label_columns: list[str]         # 值/系列名所在的列名（== 列标签）
    data_path: str                          # 该 series 落地 .parquet 的绝对路径
    source_table: str                       # 溯源：来自哪个原始表
    description: str = ""                   # 一句话说明，供计划 agent 选用
    extra_semantics: dict[str, Any] = field(default_factory=dict)  # 单位 / 格式 / 小数位等
    dtype_info: dict[str, str] = field(default_factory=dict)        # 列名 -> 类型描述

    def __post_init__(self) -> None:
        # data_path 统一用绝对 Posix 字符串，方便生成跨平台 self-contained 代码
        if self.data_path and "\\" in self.data_path:
            self.data_path = str(Path(self.data_path).as_posix())

    def label_columns(self) -> list[str]:
        """全部可用列（行标签列 + 列标签列），供 plan 校验 x_axis/y_axis 引用。"""
        cols = list(self.column_label_columns)
        if self.row_label_column and self.row_label_column not in cols:
            cols.insert(0, self.row_label_column)
        return cols


@dataclass
class SeriesCatalog:
    """series 目录：一个数据会话（一个会话目录）的全部 series。"""

    datasets_dir: str
    series: list[SemanticSeries] = field(default_factory=list)

    # ---- 查询 ----
    def by_id(self, series_id: str) -> SemanticSeries | None:
        """按 series_id 查找，找不到返回 None。"""
        return next((s for s in self.series if s.series_id == series_id), None)

    def for_table(self, source_table: str) -> list[SemanticSeries]:
        """取来自某原始表的全部 series。"""
        return [s for s in self.series if s.source_table == source_table]

    def table_names(self) -> list[str]:
        """目录中涉及的来源表名（去重，保序）。"""
        seen: list[str] = []
        for s in self.series:
            if s.source_table not in seen:
                seen.append(s.source_table)
        return seen

    # ---- prompt 索引（给计划 agent 看的精简视图） ----
    def to_index_list(self) -> list[dict[str, str]]:
        """输出 [source_table, series_id, axis_kind, description] 索引。"""
        return [
            {
                "source_table": s.source_table,
                "series_id": s.series_id,
                "axis_kind": s.axis_kind,
                "description": s.description,
            }
            for s in self.series
        ]

    def to_index_prompt(self) -> str:
        """索引的可读文本形式（注入 plan prompt 用）。"""
        lines = ["可用数据系列（series）:"]
        for item in self.to_index_list():
            lines.append(
                f"  - {item['series_id']} [{item['axis_kind']}]: {item['description']}"
            )
        return "\n".join(lines)

    # ---- 序列化 (manifest) ----
    def to_json(self) -> dict:
        """转为 JSON 可序列化 dict（落盘 manifest.json）。"""
        return {
            "datasets_dir": self.datasets_dir,
            "series": [
                {
                    "series_id": s.series_id,
                    "name": s.name,
                    "axis_kind": s.axis_kind,
                    "row_label_column": s.row_label_column,
                    "column_label_columns": s.column_label_columns,
                    "data_path": s.data_path,
                    "source_table": s.source_table,
                    "description": s.description,
                    "extra_semantics": s.extra_semantics,
                    "dtype_info": s.dtype_info,
                }
                for s in self.series
            ],
        }

    @classmethod
    def from_json(cls, data: dict) -> "SeriesCatalog":
        """从 to_json 的 dict 还原目录（回放/加载 manifest 用）。"""
        series = [
            SemanticSeries(
                series_id=item["series_id"],
                name=item.get("name", ""),
                axis_kind=item.get("axis_kind", "generic"),
                row_label_column=item.get("row_label_column"),
                column_label_columns=item.get("column_label_columns", []),
                data_path=item.get("data_path", ""),
                source_table=item.get("source_table", ""),
                description=item.get("description", ""),
                extra_semantics=item.get("extra_semantics", {}),
                dtype_info=item.get("dtype_info", {}),
            )
            for item in data.get("series", [])
        ]
        return cls(datasets_dir=data.get("datasets_dir", ""), series=series)

    @classmethod
    def from_manifest(cls, datasets_dir: str) -> "SeriesCatalog":
        """从会话目录的 manifest.json 加载目录。

        Args:
            datasets_dir: 会话目录（内含 manifest.json 与各 series .parquet）

        Returns:
            SeriesCatalog；目录或 manifest 不存在时返回空目录。
        """
        manifest = Path(datasets_dir) / "manifest.json"
        if not manifest.exists():
            return cls(datasets_dir=datasets_dir)
        import json

        with open(manifest, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_json({**data, "datasets_dir": str(datasets_dir)})