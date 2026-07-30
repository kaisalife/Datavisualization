"""DataSourceRegistry：Adapter 注册表。

替代 factory.py 里硬编码的 if/elif，新增数据源只需装饰器注册。
按 priority 降序匹配（数字大者优先）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from service.viz_data.adapters.base import AdapterError
from service.viz_data.ports import VizDataAdapterPort

if TYPE_CHECKING:
    from Entity import GenerateChartWithPromptRequest


Matcher = Callable[["GenerateChartWithPromptRequest"], bool]
Builder = Callable[["GenerateChartWithPromptRequest"], VizDataAdapterPort]


@dataclass(frozen=True)
class DataSourceSpec:
    """一个数据源的注册规约。"""

    name: str                # 唯一名称，如 "file" | "database"
    priority: int            # 数字大者优先匹配
    matches: Matcher         # 请求匹配函数
    build: Builder           # 构造 Adapter 的函数


class DataSourceRegistry:
    """全局 Adapter 注册表（单例模式）。"""

    _specs: list[DataSourceSpec] = []

    @classmethod
    def register(cls, spec: DataSourceSpec) -> None:
        """注册一个数据源。同名会覆盖，priority 降序排序。"""
        # 移除同名旧 spec（幂等，重复 import 也不会重复注册）
        cls._specs = [s for s in cls._specs if s.name != spec.name]
        cls._specs.append(spec)
        cls._specs.sort(key=lambda s: -s.priority)

    @classmethod
    def resolve(cls, request: "GenerateChartWithPromptRequest") -> VizDataAdapterPort:
        """按优先级找到第一个匹配的 spec 并构造 Adapter。"""
        for spec in cls._specs:
            try:
                if spec.matches(request):
                    return spec.build(request)
            except Exception:
                # matcher 抛异常视为不匹配，继续尝试下一个
                continue
        raise AdapterError(
            f"没有匹配的数据源 Adapter；已注册: {cls.list_sources()}；"
            "请检查请求参数（file_paths / db_config 等）"
        )

    @classmethod
    def list_sources(cls) -> list[str]:
        """列出所有已注册的数据源名（按优先级降序）。"""
        return [s.name for s in cls._specs]

    @classmethod
    def clear(cls) -> None:
        """清空注册表（仅供测试使用）。"""
        cls._specs = []


def register_source(*, name: str, priority: int, matches: Matcher) -> Callable[[Builder], Builder]:
    """装饰器语法糖。

    用法::

        @register_source(name="database", priority=20,
                         matches=lambda req: bool(getattr(req, "db_config", None)))
        def _build_database_adapter(req):
            return DatabaseAdapter(req.db_config, req.user_prompt)
    """

    def deco(builder: Builder) -> Builder:
        DataSourceRegistry.register(
            DataSourceSpec(name=name, priority=priority, matches=matches, build=builder)
        )
        return builder

    return deco


__all__ = [
    "DataSourceRegistry",
    "DataSourceSpec",
    "register_source",
    "Matcher",
    "Builder",
]
