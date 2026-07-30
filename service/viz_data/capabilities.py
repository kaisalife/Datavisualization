"""AdapterCapabilities 值对象。

用于 Adapter 向上层声明自己的能力，取代 isinstance 判断。
上层（service_main）根据能力位决定：是否需要注入 QueryEngine、是否支持多查询等。
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional


@dataclass(frozen=True)
class AdapterCapabilities:
    """Adapter 能力声明（不可变值对象）。

    Fields:
        needs_llm: fetch 阶段是否需要 QueryEngine（例：DatabaseAdapter 在 auto/single
            模式下需要 LLM 生成 SQL；FileAdapter 无需 LLM）
        supports_multi_query: 是否支持一次产出多条查询/多资源（对应 related_datasets）
        supports_array_form: 是否可能产出 arrays 形态（科学可视化）
        max_rows_hint: 单次拉取的行数上限提示（None 表示无提示）
        fetch_can_fail_gracefully: fetch 失败时能否被上层容忍并继续（例如数据库源不能，
            必须硬失败；文件源如果多文件里有一个坏文件，理论上可以继续）
    """

    needs_llm: bool
    supports_multi_query: bool
    supports_array_form: bool = False
    max_rows_hint: Optional[int] = None
    fetch_can_fail_gracefully: bool = True

    def to_dict(self) -> dict:
        return asdict(self)
