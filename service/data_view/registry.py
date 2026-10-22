"""数据视图插件注册表。

插件是数据视图层的唯一扩展点：新能力 = ``plugins/data_view/<name>.py`` 新文件，
核心零改动。每个文件必须暴露：

```python
VERSION = 1            # int，函数语义改动必须递增（否则缓存继续命中旧结果）
OUTPUT_SCHEMA = [...]  # 可选；声明后引擎会在执行后按它校验输出列

def apply(df, params) -> pandas.DataFrame:
    ...
```

纯函数契约：

1. 输入只有 ``df`` 和 ``params``；禁止读取磁盘/网络/随机/时间等外部状态；
2. 所有影响行为的量都从 ``params`` 显式传入，不写隐性默认值漂移；
3. 不修改传入 ``df``（返回新 DataFrame 或显式 copy）。

加载分两层：``register_source(name, source)`` 把插件源码文本变成插件对象
（免盘、可测），``scan(directory)`` 只是「列目录 + 读文本 + 调 register_source」
的薄壳。注册时做一次静态源码扫描（防御纵深）：命中禁用 token 的插件拒绝登记。
运行期不接受任何动态提交的代码——LLM 只能引用已注册的 ``name + version``。
"""
from __future__ import annotations

import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from service.observability import get_logger

try:  # 包导入 / 脚本直跑双写法
    from spec import PLUGIN_FORBIDDEN, PLUGIN_NOT_FOUND, DataViewError, plugin_dir_for_seed
except ImportError:  # pragma: no cover - 兼容脚本运行
    from .spec import PLUGIN_FORBIDDEN, PLUGIN_NOT_FOUND, DataViewError, plugin_dir_for_seed  # type: ignore

logger = get_logger(__name__)

# 静态扫描 token：插件是纯函数，出现这些即拒绝注册（防御纵深，不承诺完备）
FORBIDDEN_TOKENS = (
    "import random",
    "from random",
    "datetime.now",
    "utcnow",
    "open(",
    "requests",
    "urllib",
    "socket",
    "pathlib",
    "subprocess",
    "os.system",
    "os.environ",
    "(tempfile)",
)


@dataclass
class PluginEntry:
    """一个已注册插件。"""

    name: str
    version: int
    apply: Callable[..., Any]
    schema: list[dict[str, str]]   # OUTPUT_SCHEMA；未声明为 []
    path: str                      # 来源文件（绝对路径或 <source:name>），仅审计用


class PluginRegistry:
    """注册与查询插件；注册表为空时数据视图层照常工作。"""

    def __init__(self) -> None:
        self._plugins: dict[str, PluginEntry] = {}

    # ---- 登记：源码字符串（主路径，免盘可测） ----
    def register_source(
        self, name: str, source: str, *, origin_path: str | None = None
    ) -> PluginEntry:
        """把插件源码文本登记为插件对象。

        Args:
            name: 插件名（= 文件 stem / spec 里的 ``plugin`` 字段）。
            source: ``.py`` 文件的完整源码文本。
            origin_path: 来源文件路径，仅写进 ``PluginEntry.path`` 供审计。

        Returns:
            PluginEntry: 登记成功的插件。

        Raises:
            DataViewError: 源码命中禁用 token（``PLUGIN_FORBIDDEN``）；缺
                ``VERSION`` 或 ``apply``（``PLUGIN_NOT_FOUND``）。
        """
        name = str(name or "").strip()
        lowered = (source or "").lower()
        for token in FORBIDDEN_TOKENS:
            if token in lowered:
                raise DataViewError(
                    f"插件源码包含禁用 token（纯函数契约）: {token}", PLUGIN_FORBIDDEN
                )

        module = types.ModuleType(f"dataview_plugin_{name}")
        module.__file__ = str(origin_path or f"<source:{name}>")
        try:
            exec(compile(source, module.__file__, "exec"), module.__dict__)
        except Exception as e:
            raise DataViewError(f"插件 {name} 源码无法执行: {e}", PLUGIN_NOT_FOUND) from e

        version = getattr(module, "VERSION", None)
        apply_fn = getattr(module, "apply", None)
        if not isinstance(version, int) or not callable(apply_fn):
            raise DataViewError(f"插件缺少 VERSION(int) 或 apply(df, params)", PLUGIN_NOT_FOUND)
        schema = list(getattr(module, "OUTPUT_SCHEMA", []) or [])
        entry = PluginEntry(name=name, version=version, apply=apply_fn, schema=schema,
                            path=module.__file__)
        self._plugins[name] = entry
        return entry

    # ---- 登记：目录扫描（薄壳） ----
    def scan(self, directory: str | Path | None = None) -> dict[str, int]:
        """扫描目录下全部 ``*.py`` 并登记（单个失败不阻断其他）。

        Returns:
            dict: 名称 -> 版本。
        """
        directory = Path(directory or plugin_dir_for_seed())
        if not directory.is_dir():
            return {}
        for path in sorted(directory.glob("*.py")):
            if path.name.startswith("_"):
                continue
            try:
                self.register_source(path.stem, path.read_text(encoding="utf-8"),
                                     origin_path=str(path))
            except Exception as e:
                logger.warning(
                    "数据视图插件登记失败", file=str(path), code=getattr(e, "code", ""),
                    error=str(e)
                )
                continue
            entry = self._plugins[path.stem]
            logger.info(
                "数据视图插件已登记", plugin=path.stem, version=entry.version, file=str(path)
            )
        return self.describe()

    def register_entry(self, name: str, entry: PluginEntry) -> None:
        """测试直注入口（直接给 PluginEntry，不走源码加载）。"""
        self._plugins[name] = entry

    # ---- 查询 ----
    def get(self, name: str, version: int | None = None) -> PluginEntry:
        """按名称取插件；带 version 时必须完全一致（防语义漂移）。

        Raises:
            DataViewError: 未注册或版本不符（均为 ``PLUGIN_NOT_FOUND``）。
        """
        entry = self._plugins.get(str(name or "").strip())
        if entry is None:
            raise DataViewError(
                f"插件未注册: {name}；可用插件: {sorted(self._plugins) or '（无）'}",
                PLUGIN_NOT_FOUND,
            )
        if version is not None and entry.version != int(version):
            raise DataViewError(
                f"插件版本不符: {name} 注册版本={entry.version}，spec 声明={version}",
                PLUGIN_NOT_FOUND,
            )
        return entry

    def describe(self) -> dict[str, int]:
        """名称 -> 版本 的快照（给 agent / manifest 摘要用）。"""
        return {n: e.version for n, e in sorted(self._plugins.items())}


# 进程内复用的默认注册表（插件模块加载一次，不随任务重复扫盘）
_default_registry: PluginRegistry | None = None


def get_default_registry() -> PluginRegistry:
    """进程级默认注册表；首次调用时扫描插件目录。"""
    global _default_registry
    if _default_registry is None:
        registry = PluginRegistry()
        registry.scan()
        _default_registry = registry
    return _default_registry


def set_default_registry(registry: PluginRegistry | None) -> None:
    """测试 / 多工作目录场景直注入注册表（传 None 还原，下次重新 lazy 初始化）。"""
    global _default_registry
    _default_registry = registry
