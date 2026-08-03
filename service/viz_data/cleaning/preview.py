"""数据预览与质量检查。

从 DataFrame 生成结构化预览，供 LLM 和质量检查器使用。
质量检查器用硬规则判断数据是否"足够干净"，决定是否跳过 clean 阶段。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from pandas.api.types import infer_dtype


# ─────────────────────────── 数据结构 ───────────────────────────


@dataclass
class ColumnStat:
    """单列统计信息。"""

    name: str
    dtype: str
    null_count: int
    null_rate: float
    unique_count: int
    sample_values: list[str]

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "dtype": self.dtype,
            "null_count": self.null_count,
            "null_rate": round(self.null_rate, 4),
            "unique_count": self.unique_count,
            "sample_values": self.sample_values,
        }


@dataclass
class QualityMetrics:
    """数据质量指标。"""

    overall_null_rate: float
    dup_row_rate: float
    has_chinese_columns: bool
    has_mixed_dtypes: bool
    has_empty_rows: bool

    def to_dict(self) -> dict:
        return {
            "overall_null_rate": round(self.overall_null_rate, 4),
            "dup_row_rate": round(self.dup_row_rate, 4),
            "has_chinese_columns": self.has_chinese_columns,
            "has_mixed_dtypes": self.has_mixed_dtypes,
            "has_empty_rows": self.has_empty_rows,
        }


@dataclass
class DataPreview:
    """数据预览，供 LLM 和质量检查器使用。"""

    name: str
    row_count: int
    column_count: int
    columns: list[ColumnStat]
    sample_rows: list[dict]
    quality_metrics: QualityMetrics

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "row_count": self.row_count,
            "column_count": self.column_count,
            "columns": [c.to_dict() for c in self.columns],
            "sample_rows": self.sample_rows,
            "quality_metrics": self.quality_metrics.to_dict(),
        }

    def to_prompt_text(self) -> str:
        """生成 LLM 可读的文本预览。"""
        lines = [
            f"数据集: {self.name}",
            f"行数: {self.row_count}",
            f"列数: {self.column_count}",
            "",
            "列信息:",
        ]
        for col in self.columns:
            lines.append(
                f"  - {col.name} (类型: {col.dtype}, 空值率: {col.null_rate:.1%}, "
                f"唯一值: {col.unique_count}, 样本: {col.sample_values[:3]})"
            )
        lines.append("")
        lines.append("样本数据 (前5行):")
        for i, row in enumerate(self.sample_rows[:5]):
            lines.append(f"  行{i + 1}: {row}")
        lines.append("")
        lines.append("质量指标:")
        qm = self.quality_metrics
        lines.append(f"  总空值率: {qm.overall_null_rate:.1%}")
        lines.append(f"  重复行率: {qm.dup_row_rate:.1%}")
        lines.append(f"  中文列名: {'是' if qm.has_chinese_columns else '否'}")
        lines.append(f"  混合类型: {'是' if qm.has_mixed_dtypes else '否'}")
        lines.append(f"  空行存在: {'是' if qm.has_empty_rows else '否'}")
        return "\n".join(lines)


# ─────────────────────────── 预览生成 ───────────────────────────


def _is_chinese(text: str) -> bool:
    """检测字符串是否包含中文字符。"""
    return bool(re.search(r"[\u4e00-\u9fff]", str(text)))


def _safe_str(val: Any) -> str:
    """安全转字符串，处理 NaN/None。"""
    if val is None:
        return "null"
    if isinstance(val, float) and pd.isna(val):
        return "null"
    return str(val)


def generate_preview(
    df: pd.DataFrame, name: str = "unknown", sample_size: int = 5
) -> DataPreview:
    """从 DataFrame 生成数据预览。

    Args:
        df: 输入 DataFrame
        name: 数据集名称
        sample_size: 采样行数

    Returns:
        DataPreview 对象
    """
    row_count = len(df)
    column_count = len(df.columns)

    # 列统计
    columns: list[ColumnStat] = []
    for col_name in df.columns:
        col = df[col_name]
        null_count = int(col.isna().sum())
        # 推断实际类型
        inferred = infer_dtype(col, skipna=True)
        # 样本值（非空）
        non_null = col.dropna()
        if len(non_null) > 0:
            sample_vals = [_safe_str(v) for v in non_null.head(5).tolist()]
        else:
            sample_vals = ["null"]

        # nunique 对含 list/dict 等不可哈希类型的列会抛 TypeError
        try:
            unique_count = int(col.nunique(dropna=True))
        except TypeError:
            unique_count = len(set(str(v) for v in col.dropna()))

        columns.append(
            ColumnStat(
                name=str(col_name),
                dtype=str(inferred),
                null_count=null_count,
                null_rate=null_count / row_count if row_count > 0 else 0.0,
                unique_count=unique_count,
                sample_values=sample_vals,
            )
        )

    # 样本行
    sample_rows: list[dict] = []
    if row_count > 0:
        head = df.head(sample_size)
        for _, row in head.iterrows():
            sample_rows.append({str(k): _safe_str(v) for k, v in row.items()})

    # 质量指标
    # 总空值率
    if row_count > 0 and column_count > 0:
        total_cells = row_count * column_count
        null_cells = int(df.isna().sum().sum())
        overall_null_rate = null_cells / total_cells
    else:
        overall_null_rate = 0.0

    # 重复行率（含 list/dict 列时 duplicated 会失败，跳过）
    if row_count > 0:
        try:
            dup_count = int(df.duplicated().sum())
            dup_row_rate = dup_count / row_count
        except TypeError:
            dup_row_rate = 0.0
    else:
        dup_row_rate = 0.0

    # 中文列名
    has_chinese_columns = any(_is_chinese(str(c)) for c in df.columns)

    # 混合类型（object 列中包含多种 Python 类型）
    has_mixed_dtypes = False
    for col_name in df.columns:
        inferred = infer_dtype(df[col_name], skipna=True)
        if inferred in ("mixed", "mixed-integer"):
            has_mixed_dtypes = True
            break

    # 空行存在
    has_empty_rows = False
    if row_count > 0:
        has_empty_rows = bool(df.isna().all(axis=1).any())

    quality_metrics = QualityMetrics(
        overall_null_rate=overall_null_rate,
        dup_row_rate=dup_row_rate,
        has_chinese_columns=has_chinese_columns,
        has_mixed_dtypes=has_mixed_dtypes,
        has_empty_rows=has_empty_rows,
    )

    return DataPreview(
        name=name,
        row_count=row_count,
        column_count=column_count,
        columns=columns,
        sample_rows=sample_rows,
        quality_metrics=quality_metrics,
    )


# ─────────────────────────── 质量检查 ───────────────────────────


@dataclass
class QualityIssue:
    """单个质量问题。"""

    type: str  # high_null_rate / high_dup_rate / non_standard_columns / mixed_dtypes / empty_rows
    severity: str  # "warning" / "error"
    message: str
    affected_columns: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "severity": self.severity,
            "message": self.message,
            "affected_columns": self.affected_columns,
        }


@dataclass
class QualityResult:
    """质量检查结果。"""

    is_clean: bool
    issues: list[QualityIssue]

    def to_dict(self) -> dict:
        return {
            "is_clean": self.is_clean,
            "issues": [i.to_dict() for i in self.issues],
        }

    def to_prompt_text(self) -> str:
        if self.is_clean:
            return "数据质量良好，无需清洗。"
        lines = [f"发现 {len(self.issues)} 个质量问题:"]
        for issue in self.issues:
            lines.append(f"  [{issue.severity}] {issue.type}: {issue.message}")
            if issue.affected_columns:
                lines.append(f"    受影响列: {issue.affected_columns}")
        return "\n".join(lines)


class DataQualityChecker:
    """硬规则质量检查器，决定是否需要清洗。

    阈值可通过类属性覆盖（子类化或直接赋值）。
    """

    NULL_RATE_THRESHOLD: float = 0.05
    DUP_RATE_THRESHOLD: float = 0.01

    @classmethod
    def check(cls, preview: DataPreview) -> QualityResult:
        """检查数据预览，返回质量结果。

        Args:
            preview: 数据预览

        Returns:
            QualityResult，is_clean=True 表示无需清洗
        """
        issues: list[QualityIssue] = []
        qm = preview.quality_metrics

        # 检查空值率
        if qm.overall_null_rate > cls.NULL_RATE_THRESHOLD:
            affected = [
                c.name for c in preview.columns if c.null_rate > cls.NULL_RATE_THRESHOLD
            ]
            issues.append(
                QualityIssue(
                    type="high_null_rate",
                    severity="warning",
                    message=f"总空值率 {qm.overall_null_rate:.1%} 超过阈值 {cls.NULL_RATE_THRESHOLD:.0%}",
                    affected_columns=affected,
                )
            )

        # 检查重复率
        if qm.dup_row_rate > cls.DUP_RATE_THRESHOLD:
            issues.append(
                QualityIssue(
                    type="high_dup_rate",
                    severity="warning",
                    message=f"重复行率 {qm.dup_row_rate:.1%} 超过阈值 {cls.DUP_RATE_THRESHOLD:.0%}",
                )
            )

        # 检查中文列名
        if qm.has_chinese_columns:
            affected = [
                c.name for c in preview.columns if _is_chinese(c.name)
            ]
            issues.append(
                QualityIssue(
                    type="non_standard_columns",
                    severity="error",
                    message="存在中文列名，需要归一化为英文",
                    affected_columns=affected,
                )
            )

        # 检查混合类型
        if qm.has_mixed_dtypes:
            affected = []
            for col in preview.columns:
                if col.dtype in ("mixed", "mixed-integer"):
                    affected.append(col.name)
            issues.append(
                QualityIssue(
                    type="mixed_dtypes",
                    severity="error",
                    message="存在混合类型列，需要类型统一",
                    affected_columns=affected,
                )
            )

        # 检查空行
        if qm.has_empty_rows:
            issues.append(
                QualityIssue(
                    type="empty_rows",
                    severity="warning",
                    message="存在全空行，需要删除",
                )
            )

        return QualityResult(is_clean=len(issues) == 0, issues=issues)
