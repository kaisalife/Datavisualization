"""VizDataset 及相关数据类定义。

统一数据可视化契约：所有 Adapter 的产出、所有下游消费者（planner/chart_generator）的输入。

设计原则：
- 描述性 > 完整性：不必把所有数据搬进内存，可以只放 schema + 数据引用
- 多形态：既支持表格（图表），也支持数组（科学可视化）
- 可序列化：能 dump 成 JSON 给 LLM prompt 参考
- 自描述：LLM 读 VizDataset 就能知道怎么用
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from service.viz_data.source_descriptor import SourceDescriptor


# ============================================================
# 数据引用（避免把大数据塞进 VizDataset 本体）
# ============================================================

@dataclass
class DataRef:
    """指向具体数据位置的引用。真正读取时由 LLM 生成的代码通过 accessor 完成。"""
    kind: str                              # "parquet" | "csv" | "npy" | "npz" | "inline"
    path: Optional[str] = None             # 磁盘路径（绝对路径，跨进程用）
    inline_data: Optional[Any] = None      # 小数据可直接持有（用于 <1KB 场景）
    size_bytes: Optional[int] = None

    def to_dict(self) -> dict:
        d = {"kind": self.kind, "path": self.path, "size_bytes": self.size_bytes}
        # inline_data 只在小到可以放入 prompt 时保留
        if self.inline_data is not None and self.size_bytes is not None and self.size_bytes < 1024:
            d["inline_data"] = self.inline_data
        return {k: v for k, v in d.items() if v is not None}


# ============================================================
# 表格数据块
# ============================================================

@dataclass
class ColumnSchema:
    """单列的元信息。"""
    name: str
    dtype: str                             # "int" | "float" | "string" | "datetime" | "bool" | "category"
    semantic_role: Optional[str] = None    # "time" | "measure" | "dimension" | "id" | "geo_lat" | "geo_lon"
    nullable: bool = True
    unique_count: Optional[int] = None
    stats: Optional[dict] = None           # {"min", "max", "mean", "std"} for numeric

    def to_dict(self) -> dict:
        d = asdict(self)
        return {k: v for k, v in d.items() if v is not None}


@dataclass
class TabularBlock:
    """表格形态的数据。所有表格类图表用它。"""
    columns: list[ColumnSchema] = field(default_factory=list)
    row_count: int = 0
    preview_rows: list[list] = field(default_factory=list)
    data_ref: Optional[DataRef] = None

    def to_dict(self) -> dict:
        return {
            "row_count": self.row_count,
            "columns": [c.to_dict() for c in self.columns],
            "preview_rows": self.preview_rows,
            "data_ref": self.data_ref.to_dict() if self.data_ref else None,
        }


# ============================================================
# 数组数据块（科学可视化）
# ============================================================

@dataclass
class ArrayBlock:
    """numpy ndarray 形态的数据。科学可视化主用。"""
    name: str
    shape: tuple[int, ...]
    dtype: str
    unit: Optional[str] = None
    description: Optional[str] = None
    data_ref: Optional[DataRef] = None
    axis_labels: Optional[list[str]] = None

    def to_dict(self) -> dict:
        d = {
            "name": self.name,
            "shape": list(self.shape),
            "dtype": self.dtype,
            "unit": self.unit,
            "description": self.description,
            "axis_labels": self.axis_labels,
            "data_ref": self.data_ref.to_dict() if self.data_ref else None,
        }
        return {k: v for k, v in d.items() if v is not None}


# ============================================================
# 语义提示
# ============================================================

@dataclass
class SemanticHints:
    """LLM 读 hints 就能猜到怎么可视化。"""
    time_column: Optional[str] = None
    category_columns: list[str] = field(default_factory=list)
    measure_columns: list[str] = field(default_factory=list)
    natural_groupings: list[dict] = field(default_factory=list)
    detected_patterns: list[str] = field(default_factory=list)
    user_intent: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        return {k: v for k, v in d.items() if v not in (None, [], {})}


# ============================================================
# 数据访问器
# ============================================================

@dataclass
class DataAccessor:
    """LLM 生成的图表代码通过 accessor 拿数据。"""
    accessor_id: str
    signature: str
    docstring: str = ""
    returns_description: str = ""
    code_file: Optional[str] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v not in (None, "")}


# ============================================================
# VizDataset 顶层
# ============================================================

@dataclass
class VizDataset:
    """可视化领域的规范化数据结构。所有 adapter 的产出。"""
    dataset_id: str
    name: str
    source_kind: str                                    # "file" | "database" | "code"
    source_meta: dict = field(default_factory=dict)     # 已脱敏
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    primary_form: str = "tabular"                       # "tabular" | "arrays" | "hybrid"
    tabular: Optional[TabularBlock] = None
    arrays: dict[str, ArrayBlock] = field(default_factory=dict)
    semantic_hints: SemanticHints = field(default_factory=SemanticHints)
    accessors: list[DataAccessor] = field(default_factory=list)
    related_datasets: list["VizDataset"] = field(default_factory=list)  # 次级数据集（多文件上传）
    descriptor: Optional["SourceDescriptor"] = None     # ★ 脱敏数据源描述（供上层派生命名/日志）
    _temp_dir: Optional[str] = None                     # 临时目录路径（cleanup 用）

    # -------- 序列化 --------
    def to_dict(self, include_related: bool = True) -> dict:
        d = {
            "dataset_id": self.dataset_id,
            "name": self.name,
            "source_kind": self.source_kind,
            "source_meta": self.source_meta,
            "created_at": self.created_at,
            "primary_form": self.primary_form,
            "tabular": self.tabular.to_dict() if self.tabular else None,
            "arrays": {k: v.to_dict() for k, v in self.arrays.items()},
            "semantic_hints": self.semantic_hints.to_dict(),
            "accessors": [a.to_dict() for a in self.accessors],
        }
        if include_related and self.related_datasets:
            d["related_datasets"] = [r.to_dict(include_related=False) for r in self.related_datasets]
        return d

    def to_prompt_json(self, indent: int = 2, include_related: bool = True) -> str:
        """精简 JSON，供 LLM prompt 使用（不含大数据）。"""
        d = self.to_dict(include_related=include_related)
        # 过滤空字段
        d = {k: v for k, v in d.items() if v not in (None, [], {}, "")}
        return json.dumps(d, ensure_ascii=False, indent=indent, default=str)

    # -------- 便捷读取 --------
    def all_datasets(self) -> list["VizDataset"]:
        """返回主 dataset + 所有 related 的扁平列表。"""
        return [self] + list(self.related_datasets)

    def logical_id(self) -> str:
        """派生逻辑 ID，用于 output_folder 命名等场景。

        优先使用 descriptor.logical_id（Adapter 保证脱敏），
        缺失时退化到 name 或 dataset_id。
        """
        if self.descriptor is not None:
            return self.descriptor.logical_id
        return self.name or self.dataset_id

    def primary_data_path(self) -> Optional[str]:
        """返回主数据文件路径（供 chart_generator 传给 LLM）。

        tabular 优先返回 parquet；arrays 优先返回第一个数组的 npz。
        """
        if self.tabular and self.tabular.data_ref and self.tabular.data_ref.path:
            return self.tabular.data_ref.path
        if self.arrays:
            first = next(iter(self.arrays.values()))
            if first.data_ref and first.data_ref.path:
                return first.data_ref.path
        return None

    # -------- 资源清理 --------
    def cleanup(self) -> None:
        """删除临时目录。service_main 应在 finally 块调用。

        related_datasets 通常共享同一个 _temp_dir（由 primary 挂载），
        所以只需清理 primary 的 _temp_dir 即可释放所有 parquet。
        """
        if self._temp_dir:
            temp_path = Path(self._temp_dir)
            if temp_path.exists() and temp_path.is_dir():
                try:
                    shutil.rmtree(temp_path, ignore_errors=True)
                except Exception:
                    pass
            self._temp_dir = None
        # 释放 related 的 _temp_dir 引用（虽然通常为空）
        for r in self.related_datasets:
            if r._temp_dir and r._temp_dir != self._temp_dir:
                try:
                    p = Path(r._temp_dir)
                    if p.exists() and p.is_dir():
                        shutil.rmtree(p, ignore_errors=True)
                except Exception:
                    pass
                r._temp_dir = None


# ============================================================
# RawDataBundle - Fetch 阶段中间产物
# ============================================================

@dataclass
class RawDataBundle:
    """Adapter fetch 阶段的输出，尚未标准化为 VizDataset。"""
    source_kind: str
    source_meta: dict = field(default_factory=dict)
    tabular_files: list[dict] = field(default_factory=list)
    # 每项：{"name": str, "path": str, "row_count": int, "original_source": str}
    array_files: list[dict] = field(default_factory=list)
    # 每项：{"name": str, "path": str, "shape": tuple, "dtype": str}
    fetch_context: dict = field(default_factory=dict)
    temp_dir: Optional[str] = None
