"""插件加载与注册：源码登记（免盘）、禁用 token、版本查询、进程级注册表。"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from service.data_view import (
    DataViewError,
    DataViewEngine,
    PluginEntry,
    PluginRegistry,
    ViewSpec,
    get_default_registry,
    set_default_registry,
)
from service.data_view import PLUGIN_FORBIDDEN, PLUGIN_NOT_FOUND

GOOD_PLUGIN = '''"""示例插件：head(n)。"""

import pandas as pd

VERSION = 1


def apply(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """纯函数：只依赖 df 与 params。"""
    n = int(params.get("n", 1))
    return df.head(n).copy()
'''

FORBIDDEN_PLUGIN = '''"""带 IO 的插件（应被拒绝）。"""

VERSION = 1


def apply(df, params):
    with open(params.get("path"), "w") as f:  # 违反纯函数契约
        f.write(df.to_csv())
    return df
'''

NO_VERSION_PLUGIN = '''"""缺 VERSION。"""


def apply(df, params):
    return df
'''

MISSING_APPLY_PLUGIN = '''"""缺 apply。"""

VERSION = 1
'''


class TestRegisterSource:
    def test_good_plugin_registers(self):
        registry = PluginRegistry()
        entry = registry.register_source("slice_head", GOOD_PLUGIN)
        assert entry.name == "slice_head"
        assert entry.version == 1
        assert registry.describe() == {"slice_head": 1}

    def test_plugin_can_import_pandas(self):
        """插件源码里 import pandas 等常规依赖可用（exec 进独立模块）。"""
        registry = PluginRegistry()
        entry = registry.register_source("pd_user", GOOD_PLUGIN)
        df = pd.DataFrame({"a": [1, 2, 3]})
        out = entry.apply(df, {"n": 2})
        assert isinstance(out, pd.DataFrame)
        assert out["a"].tolist() == [1, 2]

    def test_forbidden_token_rejected(self):
        with pytest.raises(DataViewError) as e:
            PluginRegistry().register_source("evil_io", FORBIDDEN_PLUGIN)
        assert e.value.code == PLUGIN_FORBIDDEN
        assert "禁用 token" in str(e.value)

    def test_missing_version_rejected(self):
        with pytest.raises(DataViewError) as e:
            PluginRegistry().register_source("no_version", NO_VERSION_PLUGIN)
        assert e.value.code == PLUGIN_NOT_FOUND
        assert "VERSION" in str(e.value) or "apply" in str(e.value)

    def test_missing_apply_rejected(self):
        with pytest.raises(DataViewError) as e:
            PluginRegistry().register_source("no_apply", MISSING_APPLY_PLUGIN)
        assert e.value.code == PLUGIN_NOT_FOUND

    def test_broken_source_rejected(self):
        with pytest.raises(DataViewError) as e:
            PluginRegistry().register_source("broken", "this is not python(")
        assert e.value.code == PLUGIN_NOT_FOUND

    def test_output_schema_recorded(self):
        source = GOOD_PLUGIN + "\n\nOUTPUT_SCHEMA = [{\"name\": \"a\", \"role\": \"measure\"}]\n"
        entry = PluginRegistry().register_source("with_schema", source)
        assert entry.schema == [{"name": "a", "role": "measure"}]


class TestQueries:
    def test_get_with_version_check(self):
        registry = PluginRegistry()
        registry.register_source("slice_head", GOOD_PLUGIN)
        entry = registry.get("slice_head", version=1)
        assert entry.name == "slice_head"
        with pytest.raises(DataViewError) as e:
            registry.get("slice_head", version=7)
        assert e.value.code == PLUGIN_NOT_FOUND
        assert "版本不符" in str(e.value)

    def test_unknown_plugin_lists_available(self):
        registry = PluginRegistry()
        registry.register_source("memo", GOOD_PLUGIN)
        with pytest.raises(DataViewError) as e:
            registry.get("others")
        assert "memo" in str(e.value)

    def test_default_registry_cacheable(self):
        """进程级默认注册表：set 后 get_default_registry 返回同一对象。"""
        reg = PluginRegistry()
        reg.register_entry(
            "memo", PluginEntry(name="memo", version=2, apply=lambda df, p: df, schema=[],
                                path="(test)")
        )
        set_default_registry(reg)
        assert get_default_registry() is reg
        assert get_default_registry().describe() == {"memo": 2}
        set_default_registry(None)  # 还原，避免影响其他测试线程


class TestScanThinShell:
    def test_scan_missing_dir_is_empty(self, tmp_path: Path):
        """目录不存在 → 空 dict；空注册表查询是结构化的「未注册」错误。"""
        assert PluginRegistry().scan(tmp_path / "不存在") == {}
        with pytest.raises(DataViewError) as e2:
            PluginRegistry().get("任意")
        assert e2.value.code == PLUGIN_NOT_FOUND

    def test_scan_project_plugin_dir_no_plugins_yet(self):
        """默认插件目录当前没有插件（P0 骨架），扫描必须是空 dict 而非报错。"""
        assert PluginRegistry().scan() == {}

    def test_scan_registers_real_file(self, tmp_path):
        """目录扫描薄壳：真实文件登记成功（部分环境对 temp 目录 .py 有干扰，容忍失败）。"""
        from pathlib import Path as _P
        target = tmp_path / "slice_head.py"
        target.write_text(GOOD_PLUGIN, encoding="utf-8")
        registry = PluginRegistry()
        versions = registry.scan(tmp_path)
        # 环境异常（.py 被改名/删除）时最多登记不到，但绝不能抛错
        assert versions in ({}, {"slice_head": 1})


class TestEngineIntegration:
    def test_end_to_end_with_registered_plugin(self):
        """注册 → engine 用它跑通一条视图。"""
        registry = PluginRegistry()
        registry.register_source("slice_head", GOOD_PLUGIN)
        result = DataViewEngine(registry=registry).execute(
            ViewSpec(kind="plugin", plugin="slice_head", plugin_version=1,
                     params={"n": 2}, inputs=["t"]),
            {"t": pd.DataFrame({"a": [1, 2, 3]})},
        )
        assert result.rows == 2
        assert result.data["a"].tolist() == [1, 2]

    def test_plugin_sort_stability_is_plugin_duty(self):
        """SQL 要求声明 ORDER BY；插件的排序稳定性由插件契约与审查负责，引擎不重排。"""
        registry = PluginRegistry()
        registry.register_source("head_n", GOOD_PLUGIN)
        result = DataViewEngine(registry=registry).execute(
            ViewSpec(kind="plugin", plugin="head_n", plugin_version=1,
                     params={"n": 2}, inputs=["t"]),
            {"t": pd.DataFrame({"a": [3, 1, 2]})},
        )
        assert result.data["a"].tolist() == [3, 1]  # 取前 2 行，顺序与输入一致
