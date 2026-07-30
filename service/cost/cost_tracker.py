"""成本追踪。

参考 claude-code cost-tracker.ts + utils/modelCost.ts。
按模型短名 + 分层（input/output 分别计价），每 1M token 人民币。
"""

import threading
from dataclasses import dataclass, field
from typing import Dict, Optional


# 每 1M token 人民币价格
MODEL_COSTS: Dict[str, Dict[str, float]] = {
    "glm-4": {"input": 0.5, "output": 1.5},
    "glm-4-plus": {"input": 5.0, "output": 15.0},
    "glm-4.5": {"input": 2.0, "output": 8.0},
    "glm-4.6": {"input": 2.0, "output": 8.0},
    "glm-4.7": {"input": 2.0, "output": 8.0},
    "glm-5": {"input": 5.0, "output": 15.0},
    "glm-4-flash": {"input": 0.1, "output": 0.1},
    "gpt-4o": {"input": 2.75, "output": 11.0},
    "gpt-4o-mini": {"input": 0.15, "output": 0.6},
    "gpt-4-turbo": {"input": 8.5, "output": 25.5},
    "gpt-4": {"input": 21.0, "output": 42.0},
    "gpt-3.5-turbo": {"input": 0.5, "output": 1.5},
    "default": {"input": 2.0, "output": 8.0},
}


def get_model_cost(model: str) -> Dict[str, float]:
    """获取模型定价。精确匹配 -> 最长前缀匹配 -> default。"""
    if not model:
        return MODEL_COSTS["default"]
    if model in MODEL_COSTS:
        return MODEL_COSTS[model]
    lowered = model.lower()
    best_key = None
    for key in MODEL_COSTS:
        if key == "default":
            continue
        if lowered.startswith(key):
            if best_key is None or len(key) > len(best_key):
                best_key = key
    if best_key:
        return MODEL_COSTS[best_key]
    return MODEL_COSTS["default"]


def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """计算单次调用成本（人民币元）。

    cost = input_tokens / 1M * input_price + output_tokens / 1M * output_price
    """
    cost = get_model_cost(model)
    return (input_tokens / 1_000_000 * cost["input"]
            + output_tokens / 1_000_000 * cost["output"])


@dataclass
class CostEntry:
    """单次调用成本记录。"""
    model: str
    input_tokens: int
    output_tokens: int
    cost_rmb: float


@dataclass
class CostTracker:
    """累计成本追踪器。"""
    _entries: list = field(default_factory=list)
    _total_input_tokens: int = 0
    _total_output_tokens: int = 0
    _total_cost_rmb: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def accumulate(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """累加一次调用的成本，返回本次成本。"""
        cost = calculate_cost(model, input_tokens, output_tokens)
        with self._lock:
            self._entries.append(CostEntry(
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_rmb=cost,
            ))
            self._total_input_tokens += input_tokens
            self._total_output_tokens += output_tokens
            self._total_cost_rmb += cost
        return cost

    def get_total_cost(self) -> float:
        """返回累计成本（人民币元）。"""
        with self._lock:
            return round(self._total_cost_rmb, 6)

    def get_total_tokens(self) -> dict:
        """返回累计 token 数。"""
        with self._lock:
            return {
                "input_tokens": self._total_input_tokens,
                "output_tokens": self._total_output_tokens,
                "total_tokens": self._total_input_tokens + self._total_output_tokens,
            }

    def get_summary(self) -> dict:
        """返回成本摘要。"""
        with self._lock:
            return {
                "total_cost_rmb": round(self._total_cost_rmb, 6),
                "total_input_tokens": self._total_input_tokens,
                "total_output_tokens": self._total_output_tokens,
                "total_calls": len(self._entries),
            }

    def get_entries(self) -> list:
        """返回所有成本记录。"""
        with self._lock:
            return list(self._entries)

    def reset(self):
        """重置（保留 lock）。"""
        with self._lock:
            self._entries.clear()
            self._total_input_tokens = 0
            self._total_output_tokens = 0
            self._total_cost_rmb = 0.0

    def __repr__(self):
        return (f"CostTracker(calls={len(self._entries)}, "
                f"cost=¥{self._total_cost_rmb:.4f}, "
                f"tokens={self._total_input_tokens + self._total_output_tokens})")
