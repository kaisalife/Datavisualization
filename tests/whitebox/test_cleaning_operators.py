"""白盒测试：清洗算子。

测试 service/viz_data/cleaning/operators.py 的 15 个算子：
P0: Dedup, Filter, RenameFields, Map, Select, AddFields, Flat, Join
P1: Sort, Limit, RemoveFields, FillNull, Group, DropNull, DropDuplicateColumns

以及注册表函数：get_operator, list_operators, OPERATOR_REGISTRY
"""
from __future__ import annotations

import pandas as pd
import pytest

from service.viz_data.cleaning.operators import (
    OPERATOR_REGISTRY,
    AddFieldsOperator,
    BaseOperator,
    DedupOperator,
    DropDuplicateColumnsOperator,
    DropNullOperator,
    FillNullOperator,
    FilterOperator,
    FlatOperator,
    GroupOperator,
    JoinOperator,
    LimitOperator,
    MapOperator,
    RemoveFieldsOperator,
    RenameFieldsOperator,
    SelectOperator,
    SortOperator,
    get_operator,
    list_operators,
)


# ============================================================
# 注册表
# ============================================================

class TestRegistry:
    """测试算子注册表。"""

    def test_list_operators_sorted(self):
        """list_operators 返回排序后的算子名列表。"""
        ops = list_operators()
        assert ops == sorted(ops)
        assert "Dedup" in ops
        assert "Join" in ops

    def test_list_operators_count(self):
        """应有 15 个算子。"""
        assert len(list_operators()) == 15

    def test_get_operator_known(self):
        """已知算子应返回类。"""
        assert get_operator("Dedup") is DedupOperator
        assert get_operator("Join") is JoinOperator

    def test_get_operator_unknown(self):
        """未知算子应返回 None。"""
        assert get_operator("NonExistent") is None

    def test_registry_contains_all(self):
        """注册表应包含所有算子。"""
        expected = {
            "Dedup", "Filter", "RenameFields", "Map", "Select",
            "AddFields", "Flat", "Join", "Sort", "Limit",
            "RemoveFields", "FillNull", "Group", "DropNull", "DropDuplicateColumns",
        }
        assert set(OPERATOR_REGISTRY.keys()) == expected


# ============================================================
# DedupOperator
# ============================================================

class TestDedupOperator:
    """测试去重算子。"""

    def test_full_dedup(self):
        """全行去重。"""
        df = pd.DataFrame({"a": [1, 1, 2], "b": ["x", "x", "y"]})
        op = DedupOperator()
        result, logs = op.run(df)
        assert len(result) == 2
        assert any("removed 1" in log for log in logs)

    def test_dedup_by_column(self):
        """按指定列去重。"""
        df = pd.DataFrame({"id": [1, 1, 2], "v": ["a", "b", "c"]})
        op = DedupOperator(by=["id"])
        result, logs = op.run(df)
        assert len(result) == 2

    def test_dedup_by_missing_column(self):
        """by 中包含不存在的列时应跳过。"""
        df = pd.DataFrame({"a": [1, 2]})
        op = DedupOperator(by=["nonexistent"])
        result, _ = op.run(df)
        assert len(result) == 2

    def test_dedup_no_duplicates(self):
        """无重复时行数不变。"""
        df = pd.DataFrame({"a": [1, 2, 3]})
        op = DedupOperator()
        result, _ = op.run(df)
        assert len(result) == 3

    def test_dedup_with_list_column(self):
        """含 list 列时应先转字符串再去重。

        指定 by=["tags"] 去重，相同 tags 的行只保留一条。
        """
        df = pd.DataFrame({
            "tags": [["a", "b"], ["a", "b"], ["c"]],
            "id": [1, 2, 3],
        })
        op = DedupOperator(by=["tags"])
        result, _ = op.run(df)
        # 前两行 tags 相同 -> 去重后 2 行
        assert len(result) == 2

    def test_dedup_does_not_mutate_input(self):
        """去重不应修改原始 DataFrame。"""
        df = pd.DataFrame({"a": [1, 1, 2]})
        original_len = len(df)
        op = DedupOperator()
        op.run(df)
        assert len(df) == original_len


# ============================================================
# FilterOperator
# ============================================================

class TestFilterOperator:
    """测试条件过滤算子。"""

    def test_filter_condition(self):
        """条件表达式过滤。"""
        df = pd.DataFrame({"amount": [10, 50, 100, 5]})
        op = FilterOperator(condition="row['amount'] > 20")
        result, logs = op.run(df)
        assert len(result) == 2
        assert all(result["amount"] > 20)

    def test_filter_drop_null(self):
        """drop_null 删除含空值的行。"""
        df = pd.DataFrame({"a": [1, None, 3], "b": ["x", "y", None]})
        op = FilterOperator(drop_null=True)
        result, _ = op.run(df)
        assert len(result) == 1

    def test_filter_drop_empty(self):
        """drop_empty 删除全空行。"""
        df = pd.DataFrame({"a": [1, None, 3], "b": ["x", None, "z"]})
        op = FilterOperator(drop_empty=True)
        result, _ = op.run(df)
        assert len(result) == 2

    def test_filter_no_action(self):
        """无参数时不做任何操作。"""
        df = pd.DataFrame({"a": [1, 2]})
        op = FilterOperator()
        result, logs = op.run(df)
        assert len(result) == 2
        assert any("no action" in log for log in logs)

    def test_filter_combined(self):
        """drop_empty + condition 组合。"""
        df = pd.DataFrame({"a": [1, None, 3, 5], "b": ["x", None, "z", "w"]})
        op = FilterOperator(drop_empty=True, condition="row['a'] > 2")
        result, _ = op.run(df)
        assert len(result) == 2


# ============================================================
# RenameFieldsOperator
# ============================================================

class TestRenameFieldsOperator:
    """测试列名重命名算子。"""

    def test_rename_with_mapping(self):
        """mapping 字典重命名。"""
        df = pd.DataFrame({"old_name": [1], "keep": [2]})
        op = RenameFieldsOperator(mapping={"old_name": "new_name"})
        result, _ = op.run(df)
        assert "new_name" in result.columns
        assert "old_name" not in result.columns
        assert "keep" in result.columns

    def test_rename_missing_column(self):
        """不存在的列应在日志中警告。"""
        df = pd.DataFrame({"a": [1]})
        op = RenameFieldsOperator(mapping={"nonexistent": "new"})
        result, logs = op.run(df)
        assert "a" in result.columns
        assert any("missing" in log for log in logs)

    def test_rename_with_kwargs(self):
        """kwargs 风格重命名。"""
        df = pd.DataFrame({"old": [1]})
        op = RenameFieldsOperator(old="new")
        result, _ = op.run(df)
        assert "new" in result.columns


# ============================================================
# MapOperator
# ============================================================

class TestMapOperator:
    """测试类型转换算子。"""

    def test_to_float(self):
        """to_float 转换。"""
        df = pd.DataFrame({"a": ["1.5", "2.3", "abc"]})
        op = MapOperator(field="a", func="to_float")
        result, _ = op.run(df)
        assert result["a"].iloc[0] == 1.5
        # errors=coerce -> abc 变 NaN
        assert pd.isna(result["a"].iloc[2])

    def test_to_int(self):
        """to_int 转换。"""
        df = pd.DataFrame({"a": ["1", "2", "3"]})
        op = MapOperator(field="a", func="to_int")
        result, _ = op.run(df)
        assert result["a"].dtype.name == "Int64"

    def test_to_str(self):
        """to_str 转换。"""
        df = pd.DataFrame({"a": [1, 2, 3]})
        op = MapOperator(field="a", func="to_str")
        result, _ = op.run(df)
        # pandas 3.0 返回 StringDtype，旧版返回 object
        assert pd.api.types.is_string_dtype(result["a"])

    def test_strip(self):
        """strip 去除空白。"""
        df = pd.DataFrame({"a": ["  hello  ", "  world  "]})
        op = MapOperator(field="a", func="strip")
        result, _ = op.run(df)
        assert result["a"].iloc[0] == "hello"

    def test_unknown_func(self):
        """未知函数应在日志中警告。"""
        df = pd.DataFrame({"a": [1]})
        op = MapOperator(field="a", func="nonexistent_func")
        result, logs = op.run(df)
        assert any("unknown func" in log for log in logs)

    def test_missing_field(self):
        """不存在的列应在日志中警告。"""
        df = pd.DataFrame({"a": [1]})
        op = MapOperator(field="nonexistent", func="to_str")
        result, logs = op.run(df)
        assert any("not found" in log for log in logs)

    def test_custom_expr(self):
        """自定义表达式。"""
        df = pd.DataFrame({"a": ["1,000", "2,000"]})
        op = MapOperator(field="a", expr="float(str(row['a']).replace(',', ''))")
        result, _ = op.run(df)
        assert result["a"].iloc[0] == 1000.0

    def test_no_action(self):
        """无参数时无操作。"""
        df = pd.DataFrame({"a": [1]})
        op = MapOperator()
        result, logs = op.run(df)
        assert any("no action" in log for log in logs)


# ============================================================
# SelectOperator
# ============================================================

class TestSelectOperator:
    """测试列选择算子。"""

    def test_select_columns(self):
        """选择指定列。"""
        df = pd.DataFrame({"a": [1], "b": [2], "c": [3]})
        op = SelectOperator(columns=["a", "c"])
        result, _ = op.run(df)
        assert list(result.columns) == ["a", "c"]

    def test_select_missing_column(self):
        """不存在的列应在日志中警告。"""
        df = pd.DataFrame({"a": [1]})
        op = SelectOperator(columns=["a", "nonexistent"])
        result, logs = op.run(df)
        assert list(result.columns) == ["a"]
        assert any("missing" in log for log in logs)

    def test_select_empty(self):
        """空列表返回空 DataFrame。"""
        df = pd.DataFrame({"a": [1]})
        op = SelectOperator(columns=[])
        result, _ = op.run(df)
        assert len(result.columns) == 0


# ============================================================
# AddFieldsOperator
# ============================================================

class TestAddFieldsOperator:
    """测试添加计算列算子。"""

    def test_add_simple_field(self):
        """添加简单计算列。"""
        df = pd.DataFrame({"amount": [1000, 2000]})
        op = AddFieldsOperator(fields={"amount_wan": "float(row['amount']) / 10000"})
        result, _ = op.run(df)
        assert "amount_wan" in result.columns
        assert result["amount_wan"].iloc[0] == 0.1

    def test_add_multiple_fields(self):
        """添加多个计算列。"""
        df = pd.DataFrame({"date": ["2024-01-01", "2025-06-15"]})
        op = AddFieldsOperator(fields={
            "year": "str(row['date'])[:4]",
            "month": "str(row['date'])[5:7]",
        })
        result, _ = op.run(df)
        assert result["year"].iloc[0] == "2024"
        assert result["month"].iloc[1] == "06"

    def test_add_field_error(self):
        """表达式出错时在日志中记录 ERROR。"""
        df = pd.DataFrame({"a": [1]})
        op = AddFieldsOperator(fields={"bad": "row['nonexistent'] / 0"})
        result, logs = op.run(df)
        assert any("ERROR" in log for log in logs)


# ============================================================
# FlatOperator
# ============================================================

class TestFlatOperator:
    """测试展开嵌套结构算子。"""

    def test_flatten_list_column(self):
        """展开 list 列。"""
        df = pd.DataFrame({"id": [1, 2], "tags": [["a", "b"], ["c"]]})
        op = FlatOperator(key="tags")
        result, _ = op.run(df)
        assert len(result) == 3
        assert list(result["tags"]) == ["a", "b", "c"]

    def test_flatten_json_string(self):
        """展开 JSON 字符串列。"""
        df = pd.DataFrame({"id": [1], "tags": ['["x", "y"]']})
        op = FlatOperator(key="tags")
        result, _ = op.run(df)
        assert len(result) == 2

    def test_flatten_with_target_key(self):
        """指定 target_key 重命名展开列。"""
        df = pd.DataFrame({"id": [1], "tags": [["a", "b"]]})
        op = FlatOperator(key="tags", target_key="tag")
        result, _ = op.run(df)
        assert "tag" in result.columns
        assert "tags" not in result.columns

    def test_flatten_missing_column(self):
        """不存在的列应在日志中警告。"""
        df = pd.DataFrame({"a": [1]})
        op = FlatOperator(key="nonexistent")
        result, logs = op.run(df)
        assert any("not found" in log for log in logs)


# ============================================================
# JoinOperator
# ============================================================

class TestJoinOperator:
    """测试多源关联算子。"""

    def test_left_join(self):
        """left join 基本功能。"""
        left = pd.DataFrame({"id": [1, 2, 3], "name": ["a", "b", "c"]})
        right = pd.DataFrame({"id": [1, 2], "value": [10, 20]})
        op = JoinOperator(left="left", right="right", on="id", how="left")
        result, logs = op.run(left, inputs={"left": left, "right": right})
        assert len(result) == 3
        assert "value" in result.columns

    def test_inner_join(self):
        """inner join。"""
        left = pd.DataFrame({"id": [1, 2, 3], "name": ["a", "b", "c"]})
        right = pd.DataFrame({"id": [1, 2], "value": [10, 20]})
        op = JoinOperator(left="left", right="right", on="id", how="inner")
        result, _ = op.run(left, inputs={"left": left, "right": right})
        assert len(result) == 2

    def test_join_no_inputs(self):
        """无 inputs 时应警告。"""
        df = pd.DataFrame({"id": [1]})
        op = JoinOperator(left="a", right="b", on="id")
        result, logs = op.run(df)
        assert any("no inputs" in log for log in logs)

    def test_join_missing_input(self):
        """inputs 中缺少 left/right 时应警告。"""
        df = pd.DataFrame({"id": [1]})
        op = JoinOperator(left="a", right="b", on="id")
        result, logs = op.run(df, inputs={"a": df})
        assert any("not found" in log for log in logs)

    def test_join_missing_on_column(self):
        """on 列不存在时应报错。"""
        left = pd.DataFrame({"id": [1]})
        right = pd.DataFrame({"key": [1]})
        op = JoinOperator(left="l", right="r", on="id")
        result, logs = op.run(left, inputs={"l": left, "r": right})
        assert any("missing" in log for log in logs)

    def test_join_on_list(self):
        """on 参数支持列表。"""
        left = pd.DataFrame({"a": [1], "b": [2], "v": ["x"]})
        right = pd.DataFrame({"a": [1], "b": [2], "w": ["y"]})
        op = JoinOperator(left="l", right="r", on=["a", "b"], how="inner")
        result, _ = op.run(left, inputs={"l": left, "r": right})
        assert len(result) == 1
        assert "w" in result.columns


# ============================================================
# SortOperator
# ============================================================

class TestSortOperator:
    """测试排序算子。"""

    def test_sort_ascending(self):
        """升序排序。"""
        df = pd.DataFrame({"a": [3, 1, 2]})
        op = SortOperator(by="a", ascending=True)
        result, _ = op.run(df)
        assert list(result["a"]) == [1, 2, 3]

    def test_sort_descending(self):
        """降序排序。"""
        df = pd.DataFrame({"a": [3, 1, 2]})
        op = SortOperator(by="a", ascending=False)
        result, _ = op.run(df)
        assert list(result["a"]) == [3, 2, 1]

    def test_sort_by_list(self):
        """多列排序。"""
        df = pd.DataFrame({"a": [1, 1, 2], "b": [3, 1, 2]})
        op = SortOperator(by=["a", "b"], ascending=True)
        result, _ = op.run(df)
        assert list(result["b"]) == [1, 3, 2]

    def test_sort_missing_column(self):
        """排序列不存在时警告。"""
        df = pd.DataFrame({"a": [1]})
        op = SortOperator(by="nonexistent")
        result, logs = op.run(df)
        assert any("no valid" in log for log in logs)


# ============================================================
# LimitOperator
# ============================================================

class TestLimitOperator:
    """测试截断行数算子。"""

    def test_limit_n(self):
        """截断到 n 行。"""
        df = pd.DataFrame({"a": list(range(10))})
        op = LimitOperator(n=3)
        result, _ = op.run(df)
        assert len(result) == 3

    def test_limit_with_skip(self):
        """跳过 skip 行后取 n 行。"""
        df = pd.DataFrame({"a": list(range(10))})
        op = LimitOperator(n=3, skip=2)
        result, _ = op.run(df)
        assert len(result) == 3
        assert result["a"].iloc[0] == 2

    def test_limit_more_than_available(self):
        """n 超过行数时返回全部。"""
        df = pd.DataFrame({"a": [1, 2]})
        op = LimitOperator(n=100)
        result, _ = op.run(df)
        assert len(result) == 2


# ============================================================
# RemoveFieldsOperator
# ============================================================

class TestRemoveFieldsOperator:
    """测试删除列算子。"""

    def test_remove_columns(self):
        """删除指定列。"""
        df = pd.DataFrame({"a": [1], "b": [2], "c": [3]})
        op = RemoveFieldsOperator(columns=["b", "c"])
        result, _ = op.run(df)
        assert list(result.columns) == ["a"]

    def test_remove_missing_column(self):
        """不存在的列应在日志中警告。"""
        df = pd.DataFrame({"a": [1]})
        op = RemoveFieldsOperator(columns=["nonexistent"])
        result, logs = op.run(df)
        assert any("missing" in log for log in logs)

    def test_remove_empty(self):
        """空列表不删除任何列。"""
        df = pd.DataFrame({"a": [1]})
        op = RemoveFieldsOperator(columns=[])
        result, _ = op.run(df)
        assert "a" in result.columns


# ============================================================
# FillNullOperator
# ============================================================

class TestFillNullOperator:
    """测试填充空值算子。"""

    def test_fill_value(self):
        """用固定值填充所有空值。"""
        df = pd.DataFrame({"a": [1, None, 3]})
        op = FillNullOperator(value=0)
        result, _ = op.run(df)
        assert result["a"].isna().sum() == 0
        assert result["a"].iloc[1] == 0

    def test_fill_map(self):
        """按列指定填充值。"""
        df = pd.DataFrame({"a": [None], "b": [None]})
        op = FillNullOperator(fill_map={"a": 0, "b": "unknown"})
        result, _ = op.run(df)
        assert result["a"].iloc[0] == 0
        assert result["b"].iloc[0] == "unknown"

    def test_fill_map_partial(self):
        """fill_map 只填充指定列。"""
        df = pd.DataFrame({"a": [None], "b": [None]})
        op = FillNullOperator(fill_map={"a": 0})
        result, _ = op.run(df)
        assert result["a"].iloc[0] == 0
        assert pd.isna(result["b"].iloc[0])

    def test_fill_no_value(self):
        """无 value 和 fill_map 时应提示。"""
        df = pd.DataFrame({"a": [1]})
        op = FillNullOperator()
        result, logs = op.run(df)
        assert any("no value" in log for log in logs)


# ============================================================
# GroupOperator
# ============================================================

class TestGroupOperator:
    """测试分组聚合算子。"""

    def test_group_sum(self):
        """分组求和。"""
        df = pd.DataFrame({
            "region": ["A", "A", "B"],
            "amount": [100, 200, 300],
        })
        op = GroupOperator(by=["region"], aggs={"amount": "sum"})
        result, _ = op.run(df)
        assert len(result) == 2
        a_row = result[result["region"] == "A"]
        assert a_row["amount"].iloc[0] == 300

    def test_group_count(self):
        """分组计数。"""
        df = pd.DataFrame({
            "region": ["A", "A", "B"],
            "amount": [100, 200, 300],
        })
        op = GroupOperator(by=["region"], aggs={"amount": "count"})
        result, _ = op.run(df)
        a_row = result[result["region"] == "A"]
        assert a_row["amount"].iloc[0] == 2

    def test_group_missing_column(self):
        """分组列不存在时警告。"""
        df = pd.DataFrame({"a": [1]})
        op = GroupOperator(by=["nonexistent"], aggs={"a": "sum"})
        result, logs = op.run(df)
        assert any("no valid" in log for log in logs)

    def test_group_unknown_agg(self):
        """未知聚合函数应报错。"""
        df = pd.DataFrame({"region": ["A"], "amount": [100]})
        op = GroupOperator(by=["region"], aggs={"amount": "unknown_func"})
        result, logs = op.run(df)
        assert any("unknown agg" in log for log in logs)


# ============================================================
# DropNullOperator
# ============================================================

class TestDropNullOperator:
    """测试删除空值行算子。"""

    def test_drop_null_any(self):
        """how=any 删除含空值的行。"""
        df = pd.DataFrame({"a": [1, None, 3], "b": ["x", "y", None]})
        op = DropNullOperator(how="any")
        result, _ = op.run(df)
        assert len(result) == 1

    def test_drop_null_all(self):
        """how=all 只删除全空行。"""
        df = pd.DataFrame({"a": [1, None, 3], "b": ["x", None, "z"]})
        op = DropNullOperator(how="all")
        result, _ = op.run(df)
        assert len(result) == 2

    def test_drop_null_subset(self):
        """subset 只检查指定列。"""
        df = pd.DataFrame({"a": [1, None, 3], "b": ["x", "y", "z"]})
        op = DropNullOperator(how="any", subset=["a"])
        result, _ = op.run(df)
        assert len(result) == 2

    def test_drop_null_subset_missing(self):
        """subset 中不存在的列应跳过。"""
        df = pd.DataFrame({"a": [1, None]})
        op = DropNullOperator(how="any", subset=["nonexistent"])
        result, _ = op.run(df)
        assert len(result) == 2


# ============================================================
# DropDuplicateColumnsOperator
# ============================================================

class TestDropDuplicateColumnsOperator:
    """测试删除重复列算子。"""

    def test_drop_right_suffix(self):
        """删除 _right 后缀的列。"""
        df = pd.DataFrame({"id": [1], "name": ["a"], "name_right": ["b"]})
        op = DropDuplicateColumnsOperator()
        result, _ = op.run(df)
        assert "name" in result.columns
        assert "name_right" not in result.columns

    def test_custom_suffix(self):
        """自定义后缀。"""
        df = pd.DataFrame({"a": [1], "a_dup": [2]})
        op = DropDuplicateColumnsOperator(suffix="_dup")
        result, _ = op.run(df)
        assert "a" in result.columns
        assert "a_dup" not in result.columns

    def test_no_duplicate_columns(self):
        """无重复列时无操作。"""
        df = pd.DataFrame({"a": [1], "b": [2]})
        op = DropDuplicateColumnsOperator()
        result, logs = op.run(df)
        assert any("no duplicate" in log for log in logs)
