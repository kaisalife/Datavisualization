"""SourceDescriptor 值对象。

脱敏后的数据源描述，供上层派生 dataset 命名、日志、UI 显示。
Adapter 必须保证 label / logical_id 不含敏感信息（密码、token 等）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


SourceKind = Literal["file", "database", "code"]


@dataclass(frozen=True)
class SourceDescriptor:
    """脱敏后的数据源描述（不可变值对象）。

    Fields:
        kind: 数据源类型（枚举）
        label: human-readable 显示名，用于日志/UI，如 "MySQL: sales_db"
        logical_id: 稳定 ID，用于 output_folder 命名，如 "db_sales_orders"
            要求：只包含字母/数字/下划线/中文，不含路径分隔符
        tags: 可选标签，供上层做筛选/统计
    """

    kind: SourceKind
    label: str
    logical_id: str
    tags: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "label": self.label,
            "logical_id": self.logical_id,
            "tags": list(self.tags),
        }
