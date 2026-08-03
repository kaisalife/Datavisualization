"""清洗算子。

参考 SmartETL processor 设计，但面向 pandas DataFrame 而非逐行处理。
每个算子接收 DataFrame，返回处理后的 DataFrame + 执行日志。

算子基类 BaseOperator:
    run(df) -> (df, logs)

P0 算子（覆盖 80% 清洗场景）:
    Dedup, Filter, RenameFields, Map, Select, AddFields, Flat, Join
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any

import pandas as pd


# ─────────────────────────── 算子基类 ───────────────────────────


class BaseOperator(ABC):
    """所有清洗算子的基类。

    参考 SmartETL Processor 设计，但面向 DataFrame 批量处理。
    """

    @abstractmethod
    def run(
        self, df: pd.DataFrame, inputs: dict[str, pd.DataFrame] | None = None
    ) -> tuple[pd.DataFrame, list[str]]:
        """执行算子。

        Args:
            df: 输入 DataFrame
            inputs: 多源 DataFrame（仅 Join 算子使用）

        Returns:
            (结果 DataFrame, 执行日志列表)
        """
        ...

    @property
    def name(self) -> str:
        return self.__class__.__name__

    def __str__(self) -> str:
        return self.name


# ─────────────────────────── P0 算子 ───────────────────────────


class DedupOperator(BaseOperator):
    """去重。

    参考 SmartETL Distinct，但面向 DataFrame。
    用法 YAML:
        operator: Dedup
        by: [id, date]   # 可选，不指定则全行去重
    """

    def __init__(self, by: list[str] | None = None, **kwargs):
        self.by = by

    def run(self, df, inputs=None):
        before = len(df)
        # 含 list/dict 等不可哈希类型的列需先转为字符串才能去重
        unhashable_cols = [c for c in df.columns if df[c].dtype == "object"
                           and df[c].apply(lambda x: isinstance(x, (list, dict))).any()]
        df = df.copy()
        for c in unhashable_cols:
            df[c] = df[c].astype(str)
        if self.by:
            available = [c for c in self.by if c in df.columns]
            df = df.drop_duplicates(subset=available if available else None)
        else:
            df = df.drop_duplicates()
        after = len(df)
        return df, [f"Dedup: {before} -> {after} (removed {before - after})"]


class FilterOperator(BaseOperator):
    """条件过滤。

    参考 SmartETL Filter，但用 Python 表达式而非 matcher 函数。
    用法 YAML:
        operator: Filter
        condition: "row['amount'] > 0 and row['date'] is not None"
        # 或简单列过滤:
        # drop_null: true      # 删除含空值的行
        # drop_empty: true     # 删除全空行
    """

    def __init__(
        self,
        condition: str | None = None,
        drop_null: bool = False,
        drop_empty: bool = False,
        **kwargs,
    ):
        self.condition = condition
        self.drop_null = drop_null
        self.drop_empty = drop_empty

    def run(self, df, inputs=None):
        before = len(df)
        logs = []

        if self.drop_empty:
            df = df.dropna(how="all")
            logs.append(f"Filter(drop_empty): {before} -> {len(df)}")

        if self.drop_null:
            df = df.dropna()
            logs.append(f"Filter(drop_null): {before} -> {len(df)}")

        if self.condition:
            # 安全执行条件表达式
            safe_globals = {"pd": pd, "len": len, "abs": abs, "str": str, "float": float, "int": int}
            mask = df.apply(
                lambda row: bool(eval(self.condition, {"row": row, **safe_globals})), axis=1
            )
            df = df[mask]
            logs.append(f"Filter(condition): {before} -> {len(df)}")

        if not logs:
            logs.append("Filter: no action")
        return df, logs


class RenameFieldsOperator(BaseOperator):
    """列名重命名。

    参考 SmartETL RenameFields，支持中文列名转英文。
    用法 YAML:
        operator: RenameFields
        mapping:
          销售额: amount
          日期: date
    """

    def __init__(self, mapping: dict[str, str] | None = None, **kwargs):
        # 也支持 SmartETL 风格的 **kwargs: RenameFields(销售额=amount)
        self.mapping = mapping or {}
        self.mapping.update(kwargs)

    def run(self, df, inputs=None):
        # 只重命名存在的列
        actual = {k: v for k, v in self.mapping.items() if k in df.columns}
        missing = [k for k in self.mapping if k not in df.columns]
        df = df.rename(columns=actual)
        logs = [f"RenameFields: {actual}"]
        if missing:
            logs.append(f"  WARNING missing columns: {missing}")
        return df, logs


class MapOperator(BaseOperator):
    """类型转换 / 值映射。

    参考 SmartETL Map，对指定列应用转换函数。
    用法 YAML:
        operator: Map
        field: amount
        func: to_float
        # 或自定义表达式:
        # expr: "float(str(row['amount']).replace(',', ''))"
    """

    BUILTIN_FUNCS = {
        "to_float": lambda x: pd.to_numeric(x, errors="coerce"),
        "to_int": lambda x: pd.to_numeric(x, errors="coerce").astype("Int64"),
        "to_str": lambda x: x.astype(str),
        "to_datetime": lambda x: pd.to_datetime(x, errors="coerce"),
        "strip": lambda x: x.astype(str).str.strip(),
        "lower": lambda x: x.astype(str).str.lower(),
        "upper": lambda x: x.astype(str).str.upper(),
    }

    def __init__(
        self, field: str | None = None, func: str | None = None, expr: str | None = None, **kwargs
    ):
        self.field = field
        self.func = func
        self.expr = expr

    def run(self, df, inputs=None):
        logs = []
        if self.field and self.field not in df.columns:
            return df, [f"Map: WARNING column '{self.field}' not found"]

        if self.func:
            func = self.BUILTIN_FUNCS.get(self.func)
            if func is None:
                return df, [f"Map: WARNING unknown func '{self.func}'"]
            df[self.field] = func(df[self.field])
            logs.append(f"Map: {self.field} -> {self.func}")

        if self.expr:
            safe_globals = {"pd": pd, "float": float, "int": int, "str": str, "len": len}
            try:
                df[self.field] = df.apply(
                    lambda row: eval(self.expr, {"row": row, **safe_globals}), axis=1
                )
                logs.append(f"Map: {self.field} <- expr")
            except Exception as e:
                logs.append(f"Map: ERROR expr '{self.expr}': {e}")

        if not logs:
            logs.append("Map: no action")
        return df, logs


class SelectOperator(BaseOperator):
    """列选择。

    参考 SmartETL Select，保留指定列。
    用法 YAML:
        operator: Select
        columns: [date, amount, product]
    """

    def __init__(self, columns: list[str] | None = None, **kwargs):
        self.columns = columns or []

    def run(self, df, inputs=None):
        available = [c for c in self.columns if c in df.columns]
        missing = [c for c in self.columns if c not in df.columns]
        df = df[available]
        logs = [f"Select: {available}"]
        if missing:
            logs.append(f"  WARNING missing: {missing}")
        return df, logs


class AddFieldsOperator(BaseOperator):
    """添加计算列。

    参考 SmartETL AddFields，用 Python 表达式计算新列。
    用法 YAML:
        operator: AddFields
        fields:
          year: "str(row['date'])[:4]"
          amount_wan: "float(row['amount']) / 10000"
    """

    def __init__(self, fields: dict[str, str] | None = None, **kwargs):
        self.fields = fields or {}

    def run(self, df, inputs=None):
        logs = []
        safe_globals = {"pd": pd, "float": float, "int": int, "str": str, "len": len, "abs": abs}
        for name, expr in self.fields.items():
            try:
                df[name] = df.apply(
                    lambda row, e=expr: eval(e, {"row": row, **safe_globals}), axis=1
                )
                logs.append(f"AddFields: {name} = {expr}")
            except Exception as e:
                logs.append(f"AddFields: ERROR {name} = {expr}: {e}")
        return df, logs


class FlatOperator(BaseOperator):
    """展开嵌套结构。

    参考 SmartETL Flat，展开列表/JSON 列。
    用法 YAML:
        operator: Flat
        key: tags          # 展开该列的列表
        target_key: tag    # 展开后的列名（可选，默认同 key）
    """

    def __init__(self, key: str | None = None, target_key: str | None = None, **kwargs):
        self.key = key
        self.target_key = target_key or key

    def run(self, df, inputs=None):
        if not self.key or self.key not in df.columns:
            return df, [f"Flat: WARNING column '{self.key}' not found"]

        before = len(df)
        # 检测列内容是否为列表/JSON 字符串
        col = df[self.key]
        # pandas 3.0 字符串列的 dtype 可能是 StringDtype 而非 object
        if col.dtype == "object" or pd.api.types.is_string_dtype(col):
            # 尝试解析 JSON 字符串为列表
            def _try_parse(v):
                if isinstance(v, list):
                    return v
                if isinstance(v, str) and v.startswith("["):
                    import json

                    try:
                        return json.loads(v)
                    except Exception:
                        return v
                return v

            df[self.key] = col.apply(_try_parse)

        df = df.explode(self.key)
        if self.target_key != self.key:
            df = df.rename(columns={self.key: self.target_key})

        after = len(df)
        return df, [f"Flat: exploded '{self.key}' ({before} -> {after} rows)"]


class JoinOperator(BaseOperator):
    """多源关联。

    参考 SmartETL Collect，用 pandas merge 实现。
    用法 YAML:
        operator: Join
        left: orders
        right: products
        on: product_id
        how: left
    """

    def __init__(
        self, left: str, right: str, on: str, how: str = "left", **kwargs
    ):
        self.left = left
        self.right = right
        self.on = on
        self.how = how

    def run(self, df, inputs=None):
        if inputs is None:
            return df, ["Join: WARNING no inputs provided"]

        left_df = inputs.get(self.left)
        right_df = inputs.get(self.right)

        if left_df is None:
            return df, [f"Join: WARNING left '{self.left}' not found in inputs"]
        if right_df is None:
            return df, [f"Join: WARNING right '{self.right}' not found in inputs"]

        before_left = len(left_df)
        before_right = len(right_df)

        # on 可以是字符串或列表
        on_cols = [self.on] if isinstance(self.on, str) else self.on

        # 检查 on 列是否存在
        missing_left = [c for c in on_cols if c not in left_df.columns]
        missing_right = [c for c in on_cols if c not in right_df.columns]
        if missing_left or missing_right:
            return df, [
                f"Join: ERROR on columns missing: left={missing_left}, right={missing_right}"
            ]

        result = left_df.merge(right_df, on=on_cols, how=self.how, suffixes=("", "_right"))
        return result, [
            f"Join: {self.left}({before_left}) + {self.right}({before_right}) "
            f"on {on_cols} ({self.how}) -> {len(result)} rows"
        ]


# ─────────────────────────── P1 算子 ───────────────────────────


class SortOperator(BaseOperator):
    """排序。

    用法 YAML:
        operator: Sort
        by: [date, amount]
        ascending: false  # 默认 true
    """

    def __init__(self, by: list[str] | str, ascending: bool = True, **kwargs):
        self.by = by if isinstance(by, list) else [by]
        self.ascending = ascending

    def run(self, df, inputs=None):
        available = [c for c in self.by if c in df.columns]
        if not available:
            return df, [f"Sort: WARNING no valid columns in {self.by}"]
        df = df.sort_values(by=available, ascending=self.ascending)
        return df, [f"Sort: by={available} ascending={self.ascending}"]


class LimitOperator(BaseOperator):
    """截断行数。

    参考 SmartETL Limit/TakeN。
    用法 YAML:
        operator: Limit
        n: 1000        # 保留前 n 行
        skip: 10       # 可选，跳过前 skip 行
    """

    def __init__(self, n: int, skip: int = 0, **kwargs):
        self.n = n
        self.skip = max(skip, 0)

    def run(self, df, inputs=None):
        before = len(df)
        df = df.iloc[self.skip : self.skip + self.n]
        return df, [f"Limit: skip={self.skip}, n={self.n} ({before} -> {len(df)})"]


class RemoveFieldsOperator(BaseOperator):
    """删除列。

    参考 SmartETL RemoveFields。
    用法 YAML:
        operator: RemoveFields
        columns: [temp_col, debug_col]
    """

    def __init__(self, columns: list[str] | None = None, **kwargs):
        self.columns = columns or []

    def run(self, df, inputs=None):
        available = [c for c in self.columns if c in df.columns]
        missing = [c for c in self.columns if c not in df.columns]
        df = df.drop(columns=available)
        logs = [f"RemoveFields: {available}"]
        if missing:
            logs.append(f"  WARNING missing: {missing}")
        return df, logs


class FillNullOperator(BaseOperator):
    """填充空值。

    用法 YAML:
        operator: FillNull
        value: 0              # 所有空值填 0
        # 或按列指定:
        # fill_map:
        #   amount: 0
        #   name: unknown
    """

    def __init__(
        self, value: Any = None, fill_map: dict[str, Any] | None = None, **kwargs
    ):
        self.value = value
        self.fill_map = fill_map or {}

    def run(self, df, inputs=None):
        before_na = int(df.isna().sum().sum())
        if self.fill_map:
            actual_map = {k: v for k, v in self.fill_map.items() if k in df.columns}
            df = df.fillna(actual_map)
            logs = [f"FillNull(map): {actual_map}"]
        elif self.value is not None:
            df = df.fillna(self.value)
            logs = [f"FillNull(value={self.value})"]
        else:
            return df, ["FillNull: no value or fill_map specified"]
        after_na = int(df.isna().sum().sum())
        logs.append(f"  filled {before_na - after_na} nulls ({before_na} -> {after_na})")
        return df, logs


class GroupOperator(BaseOperator):
    """分组聚合。

    参考 SmartETL aggs。
    用法 YAML:
        operator: Group
        by: [region, product]
        aggs:
          amount: sum      # sum/mean/count/max/min
          quantity: count
    """

    AGG_FUNCS = {"sum", "mean", "count", "max", "min", "std", "var", "median"}

    def __init__(self, by: list[str], aggs: dict[str, str], **kwargs):
        self.by = by if isinstance(by, list) else [by]
        self.aggs = aggs

    def run(self, df, inputs=None):
        available_by = [c for c in self.by if c in df.columns]
        if not available_by:
            return df, [f"Group: WARNING no valid group columns in {self.by}"]

        # 构建聚合字典
        agg_dict = {}
        for col, func in self.aggs.items():
            if col in df.columns and func in self.AGG_FUNCS:
                agg_dict[col] = func
            elif col in df.columns:
                return df, [f"Group: ERROR unknown agg func '{func}' for column '{col}'"]

        if not agg_dict:
            return df, ["Group: WARNING no valid aggregations"]

        before = len(df)
        df = df.groupby(available_by, as_index=False).agg(agg_dict)
        return df, [f"Group: by={available_by}, aggs={agg_dict} ({before} -> {len(df)})"]


class DropNullOperator(BaseOperator):
    """删除空值行。

    用法 YAML:
        operator: DropNull
        how: any    # any=含空值就删, all=全空才删
        # subset: [col1, col2]  # 可选，只检查指定列
    """

    def __init__(self, how: str = "any", subset: list[str] | None = None, **kwargs):
        self.how = how
        self.subset = subset

    def run(self, df, inputs=None):
        before = len(df)
        subset = [c for c in self.subset if c in df.columns] if self.subset else None
        df = df.dropna(how=self.how, subset=subset)
        return df, [f"DropNull: how={self.how}, subset={subset} ({before} -> {len(df)})"]


class DropDuplicateColumnsOperator(BaseOperator):
    """删除重复列（后缀 _right）。

    Join 后可能产生 _right 后缀的重复列，此算子清理它们。
    用法 YAML:
        operator: DropDuplicateColumns
        suffix: _right   # 默认 _right
    """

    def __init__(self, suffix: str = "_right", **kwargs):
        self.suffix = suffix

    def run(self, df, inputs=None):
        dup_cols = [c for c in df.columns if str(c).endswith(self.suffix)]
        if dup_cols:
            df = df.drop(columns=dup_cols)
            return df, [f"DropDuplicateColumns: removed {dup_cols}"]
        return df, ["DropDuplicateColumns: no duplicate columns found"]


# ─────────────────────────── 算子注册表 ───────────────────────────


OPERATOR_REGISTRY: dict[str, type[BaseOperator]] = {
    # P0
    "Dedup": DedupOperator,
    "Filter": FilterOperator,
    "RenameFields": RenameFieldsOperator,
    "Map": MapOperator,
    "Select": SelectOperator,
    "AddFields": AddFieldsOperator,
    "Flat": FlatOperator,
    "Join": JoinOperator,
    # P1
    "Sort": SortOperator,
    "Limit": LimitOperator,
    "RemoveFields": RemoveFieldsOperator,
    "FillNull": FillNullOperator,
    "Group": GroupOperator,
    "DropNull": DropNullOperator,
    "DropDuplicateColumns": DropDuplicateColumnsOperator,
}


def get_operator(name: str) -> type[BaseOperator] | None:
    """从注册表获取算子类。"""
    return OPERATOR_REGISTRY.get(name)


def list_operators() -> list[str]:
    """列出所有注册的算子名。"""
    return sorted(OPERATOR_REGISTRY.keys())
