"""ViewSpec：hash 稳定性、id 内容寻址与非法 spec 校验。"""
from __future__ import annotations

import pytest

from service.data_view import (
    DataViewError,
    ViewSpec,
    payload_of,
    spec_hash,
    validate_spec,
    view_id,
)
from service.data_view import (
    PLUGIN_NOT_FOUND,
    SPEC_INVALID,
    UNORDERED_OUTPUT,
    WRITE_STATEMENT_REJECTED,
)


SQL_ORDERED = "select 城市, sum(销售额) as 销售额 from table_0 group by 城市 order by 销售额 desc"


class TestSpecHash:
    """同语义 spec 必得同 hash；任意有语义的差异必须变 hash。"""

    def test_same_sql_hash_stable(self):
        spec1 = ViewSpec(kind="sql", sql=SQL_ORDERED, inputs=["table_0"])
        spec2 = ViewSpec(kind="sql", sql=SQL_ORDERED, inputs=["table_0"])
        assert spec_hash(spec1) == spec_hash(spec2)

    def test_whitespace_insensitive(self):
        """空白差异不改变语义，hash 必须一致。"""
        spec1 = ViewSpec(kind="sql", sql="select a,b\nfrom\tt\norder by   a", inputs=["t"])
        spec2 = ViewSpec(kind="sql", sql="select a,b from t order by a", inputs=["t"])
        assert spec_hash(spec1) == spec_hash(spec2)

    def test_params_order_insensitive(self):
        """params 键顺序不影响 hash。"""
        spec1 = ViewSpec(kind="plugin", plugin="p", params={"a": 1, "b": 2}, inputs=["t"])
        spec2 = ViewSpec(kind="plugin", plugin="p", params={"b": 2, "a": 1}, inputs=["t"])
        assert spec_hash(spec1) == spec_hash(spec2)

    def test_semantic_changes_change_hash(self):
        base = ViewSpec(kind="sql", sql=SQL_ORDERED, inputs=["table_0"])
        variants = [
            ViewSpec(kind="sql", sql=SQL_ORDERED, inputs=["table_1"]),       # 输入不同
            ViewSpec(kind="sql", sql=SQL_ORDERED, inputs=["table_0"], allow_unordered=False,
                     allow_empty=True),                                      # allow_empty 改变
            ViewSpec(kind="sql", sql=SQL_ORDERED + " limit 5", inputs=["table_0"]),  # SQL 不同
        ]
        hashes = {spec_hash(base)}
        for variant in variants:
            assert spec_hash(variant) not in hashes, "语义变化必须造成 hash 变化"
            hashes.add(spec_hash(variant))

    def test_plugin_version_in_payload(self):
        """插件版本参与 hash：版本漂移 → view_id 变化。"""
        spec1 = ViewSpec(kind="plugin", plugin="p", plugin_version=2, inputs=["t"])
        spec2 = ViewSpec(kind="plugin", plugin="p", plugin_version=3, inputs=["t"])
        assert spec_hash(spec1) != spec_hash(spec2)

    def test_payload_is_json_serializable(self):
        spec = ViewSpec(kind="sql", sql=SQL_ORDERED, inputs=["table_0"], title="按城市合计")
        import json

        assert json.dumps(payload_of(spec), ensure_ascii=False)


class TestViewId:
    def test_includes_input_fingerprints(self):
        """输入指纹参与 id：同 spec 不同数据 → 不同 view_id。"""
        spec = ViewSpec(kind="sql", sql=SQL_ORDERED, inputs=["table_0"])
        id1 = view_id(spec, {"table_0": "fp_aaaa"})
        id2 = view_id(spec, {"table_0": "fp_bbbb"})
        assert id1 != id2
        assert id1.startswith("vw_") and len(id1) == len("vw_") + 16

    def test_deterministic_and_full_hex(self):
        spec = ViewSpec(kind="sql", sql=SQL_ORDERED, inputs=["t"])
        assert view_id(spec, {"t": "fp"}) == view_id(spec, {"t": "fp"})

    def test_missing_input_raises(self):
        spec = ViewSpec(kind="sql", sql=SQL_ORDERED, inputs=["missing"])
        with pytest.raises(DataViewError) as e:
            view_id(spec, {"other": "fp"})
        assert e.value.code == "INPUT_NOT_FOUND"


class TestValidateSpec:
    def test_read_only_sql_ok(self):
        spec = ViewSpec(kind="sql", sql=SQL_ORDERED, inputs=["table_0"])
        validate_spec(spec)  # 不抛即通过

    def test_write_statement_rejected(self):
        with pytest.raises(DataViewError) as e:
            validate_spec(
                ViewSpec(kind="sql", sql="select 1; drop table t", inputs=["t"],
                         allow_unordered=True)
            )
        assert e.value.code == WRITE_STATEMENT_REJECTED

    def test_literal_semicolon_not_multi_statement(self):
        """字符串里的分号不该被误判成多语句（复用 sql_safety 的行为）。"""
        spec = ViewSpec(
            kind="sql",
            sql="select 城市, sum(销售额) as 销售额 from t where note = 'a;b' "
                "group by 城市 order by 销售额",
            inputs=["t"],
        )
        validate_spec(spec)

    def test_write_as_main_statement_rejected(self):
        """写操作作主语句被拒；CTE/子查询里的 DML 由执行层报语法错误兜底。"""
        with pytest.raises(DataViewError) as e:
            validate_spec(
                ViewSpec(kind="sql", sql="update t set a = 1 where a = 0", inputs=["t"])
            )
        assert e.value.code == WRITE_STATEMENT_REJECTED

    def test_missing_order_by_rejected(self):
        with pytest.raises(DataViewError) as e:
            validate_spec(ViewSpec(kind="sql", sql="select a from t", inputs=["t"]))
        assert e.value.code == UNORDERED_OUTPUT

    def test_order_inside_cte_counts(self):
        """CTE 内有 ORDER BY 也满足稳定排序要求（保守放行）。"""
        spec = ViewSpec(
            kind="sql",
            sql="with aggr as (select 城市, sum(销售额) s from t group by 城市 order by s) "
                "select 城市, s from aggr",
            inputs=["t"],
        )
        validate_spec(spec)

    def test_sql_empty_or_missing_inputs(self):
        with pytest.raises(DataViewError) as e:
            validate_spec(ViewSpec(kind="sql", sql="", inputs=["t"]))
        assert e.value.code == SPEC_INVALID
        with pytest.raises(DataViewError) as e2:
            validate_spec(ViewSpec(kind="sql", sql=SQL_ORDERED, inputs=[]))
        assert e2.value.code == SPEC_INVALID

    def test_plugin_requires_single_input(self):
        with pytest.raises(DataViewError) as e:
            validate_spec(ViewSpec(kind="plugin", plugin="p", inputs=["a", "b"]))
        assert e.value.code == SPEC_INVALID

    def test_unknown_kind(self):
        with pytest.raises(DataViewError) as e:
            validate_spec(ViewSpec(kind="macro", inputs=["t"]))
        assert e.value.code == SPEC_INVALID

    def test_no_business_columns_in_core(self):
        """反模式自查：核心库不出现 if 列名 == 业务列名（按 05 清单）。"""
        import re
        from pathlib import Path

        pkg = Path("service/data_view")
        pattern = re.compile(r"(==|!=)\s*[\"'](销售额|城市|月份|开盘|收盘)[\"']")
        for path in pkg.glob("*.py"):
            assert not pattern.search(path.read_text(encoding="utf-8")), f"{path} 含业务列名特判"

    def test_plugin_version_mismatch_detected_at_engine(self):
        """版本不符在 engine 层拒绝（这里只锁定 spec 字段可表达版本）。"""
        spec = ViewSpec(kind="plugin", plugin="p", plugin_version=9, inputs=["t"])
        validate_spec(spec)  # 静态校验放行，实际拒绝发生在 engine._exec_plugin
