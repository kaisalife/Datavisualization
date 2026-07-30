import time
from dataclasses import dataclass, field
from typing import Optional, Union

try:
    import tiktoken
except ImportError:
    tiktoken = None


COMPLETION_THRESHOLD = 0.9
# 单次调用增量 tokens 小于此值算"低产出"。图表生成场景 output 短是正常的，
# 阈值不能过高，否则触发假阳性 diminishing_returns。
DIMINISHING_THRESHOLD = 100
# 连续多少次低产出才停止。数据可视化场景多次生成短代码属正常，需要更宽松。
DIMINISHING_CONSECUTIVE_LIMIT = 5
DEFAULT_CONTEXT_WINDOW = 200000

MODEL_CONTEXT_WINDOWS = {
    "glm-4": 128000,
    "glm-4-plus": 128000,
    "glm-4.5": 128000,
    "glm-4.6": 128000,
    "glm-4.7": 128000,
    "glm-5": 128000,
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
    "gpt-4-turbo": 128000,
    "gpt-4": 8192,
    "gpt-3.5-turbo": 16385,
}

MODEL_MAX_OUTPUT_TOKENS = {
    "glm-4": 4096,
    "glm-4-plus": 4096,
    "glm-4.5": 4096,
    "glm-4.6": 4096,
    "glm-4.7": 4096,
    "glm-5": 8192,
    "gpt-4o": 16384,
    "gpt-4o-mini": 16384,
    "gpt-4-turbo": 4096,
    "gpt-4": 8192,
    "default": 4096,
}

_encoders = {}


def _get_encoder(model: str = "gpt-4o"):
    if tiktoken is None:
        return None
    if model not in _encoders:
        try:
            if "gpt-4" in model or "gpt-3.5" in model:
                _encoders[model] = tiktoken.encoding_for_model(model)
            else:
                _encoders[model] = tiktoken.get_encoding("cl100k_base")
        except Exception:
            try:
                _encoders[model] = tiktoken.get_encoding("cl100k_base")
            except Exception:
                _encoders[model] = None
    return _encoders[model]


def count_tokens(text: str, model: str = "gpt-4o") -> int:
    """计算文本的 token 数。tiktoken 不可用时回退字符数估算。"""
    if not text:
        return 0
    encoder = _get_encoder(model)
    if encoder is not None:
        try:
            return len(encoder.encode(text))
        except Exception:
            pass
    return max(1, len(text) // 3)


def count_messages_tokens(messages, model: str = "gpt-4o") -> int:
    """计算消息列表的 token 总数。"""
    total = 0
    for msg in messages:
        content = getattr(msg, "content", str(msg))
        total += count_tokens(content, model) + 4
    return total


def get_context_window_for_model(model: str) -> int:
    """解析模型上下文窗口大小。

    解析链：精确匹配 -> 前缀匹配 -> [1m] 后缀 -> 默认 200k。
    """
    if not model:
        return DEFAULT_CONTEXT_WINDOW

    if model in MODEL_CONTEXT_WINDOWS:
        return MODEL_CONTEXT_WINDOWS[model]

    lowered = model.lower()
    if lowered.endswith("[1m]"):
        return 1000000

    for key, window in MODEL_CONTEXT_WINDOWS.items():
        if lowered.startswith(key):
            return window

    return DEFAULT_CONTEXT_WINDOW


def get_model_max_output_tokens(model: str) -> int:
    """获取模型最大输出 token 数。"""
    if not model:
        return MODEL_MAX_OUTPUT_TOKENS["default"]
    if model in MODEL_MAX_OUTPUT_TOKENS:
        return MODEL_MAX_OUTPUT_TOKENS[model]
    lowered = model.lower()
    for key, tokens in MODEL_MAX_OUTPUT_TOKENS.items():
        if lowered.startswith(key):
            return tokens
    return MODEL_MAX_OUTPUT_TOKENS["default"]


@dataclass
class ContinueDecision:
    """继续执行的决策。"""
    pass


@dataclass
class StopDecision:
    """停止执行的决策。"""
    reason: str
    used_tokens: int = 0
    limit_tokens: int = 0


BudgetDecision = Union[ContinueDecision, StopDecision]


@dataclass
class BudgetTracker:
    """Token 预算追踪器。"""
    continuation_count: int = 0
    last_delta_tokens: int = 0
    last_global_turn_tokens: int = 0
    started_at: float = field(default_factory=time.time)
    diminishing_streak: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0

    def record_turn(self, input_tokens: int, output_tokens: int):
        """记录一次 LLM 调用的 token 用量。"""
        delta = input_tokens + output_tokens
        self.last_delta_tokens = delta
        self.last_global_turn_tokens = delta
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.continuation_count += 1

        if delta < DIMINISHING_THRESHOLD:
            self.diminishing_streak += 1
        else:
            self.diminishing_streak = 0

    def get_total_used(self) -> int:
        return self.total_input_tokens + self.total_output_tokens


def check_budget(tracker: BudgetTracker, used: int, limit: int) -> BudgetDecision:
    """检查 token 预算，返回继续或停止决策。

    停止条件：
    1. used >= limit * COMPLETION_THRESHOLD (90%) -> budget_exceeded
    2. diminishing_streak >= DIMINISHING_CONSECUTIVE_LIMIT (连续3次 delta<500) -> diminishing_returns
    """
    if limit <= 0:
        return ContinueDecision()

    if used >= int(limit * COMPLETION_THRESHOLD):
        return StopDecision(
            reason="budget_exceeded",
            used_tokens=used,
            limit_tokens=limit,
        )

    if tracker.diminishing_streak >= DIMINISHING_CONSECUTIVE_LIMIT:
        return StopDecision(
            reason="diminishing_returns",
            used_tokens=used,
            limit_tokens=limit,
        )

    return ContinueDecision()


def create_tracker() -> BudgetTracker:
    return BudgetTracker()
