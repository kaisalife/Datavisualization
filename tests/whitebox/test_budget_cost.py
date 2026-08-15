"""token_budget 与 cost_tracker 单元测试。

覆盖纯逻辑：token 计数、上下文窗口解析、预算决策、成本计算与累计、线程安全。
不依赖 LLM / 网络。
"""
from service.runtime.budget.token_budget import (
    BudgetTracker,
    ContinueDecision,
    StopDecision,
    check_budget,
    count_tokens,
    count_messages_tokens,
    get_context_window_for_model,
    get_model_max_output_tokens,
    DEFAULT_CONTEXT_WINDOW,
    DIMINISHING_CONSECUTIVE_LIMIT,
    COMPLETION_THRESHOLD,
)
from service.runtime.cost.cost_tracker import (
    CostTracker,
    calculate_cost,
    get_model_cost,
    MODEL_COSTS,
)


# ===== token_budget =====

class TestCountTokens:
    def test_empty(self):
        assert count_tokens("") == 0
        assert count_tokens(None) == 0

    def test_nonempty_positive(self):
        assert count_tokens("hello world") > 0

    def test_longer_more_tokens(self):
        short = count_tokens("a")
        long = count_tokens("a" * 1000)
        assert long > short


class TestCountMessagesTokens:
    def test_list_with_overhead(self):
        class Msg:
            def __init__(self, c):
                self.content = c
        msgs = [Msg("hello"), Msg("world")]
        total = count_messages_tokens(msgs)
        # 每条消息 +4 开销
        assert total == count_tokens("hello") + count_tokens("world") + 8


class TestContextWindow:
    def test_exact(self):
        assert get_context_window_for_model("gpt-4o") == 128000
        assert get_context_window_for_model("gpt-4") == 8192

    def test_prefix(self):
        assert get_context_window_for_model("gpt-4o-2024-08") == 128000

    def test_1m_suffix(self):
        assert get_context_window_for_model("some-model[1m]") == 1000000

    def test_default(self):
        assert get_context_window_for_model("unknown-model") == DEFAULT_CONTEXT_WINDOW
        assert get_context_window_for_model("") == DEFAULT_CONTEXT_WINDOW


class TestMaxOutput:
    def test_known(self):
        assert get_model_max_output_tokens("gpt-4o") == 16384

    def test_default(self):
        assert get_model_max_output_tokens("unknown") == 4096
        assert get_model_max_output_tokens("") == 4096


class TestBudgetTracker:
    def test_record_turn_accumulates(self):
        t = BudgetTracker()
        t.record_turn(100, 50)
        assert t.total_input_tokens == 100
        assert t.total_output_tokens == 50
        assert t.get_total_used() == 150
        assert t.continuation_count == 1
        t.record_turn(200, 80)
        assert t.get_total_used() == 430
        assert t.continuation_count == 2

    def test_diminishing_streak(self):
        t = BudgetTracker()
        for _ in range(3):
            t.record_turn(40, 10)  # delta=50 < DIMINISHING_THRESHOLD(100)
        assert t.diminishing_streak == 3
        t.record_turn(500, 500)  # 大增量重置
        assert t.diminishing_streak == 0


class TestCheckBudget:
    def test_continue(self):
        t = BudgetTracker()
        assert isinstance(check_budget(t, 100, 1000), ContinueDecision)

    def test_budget_exceeded(self):
        t = BudgetTracker()
        used = int(1000 * COMPLETION_THRESHOLD)
        d = check_budget(t, used, 1000)
        assert isinstance(d, StopDecision)
        assert d.reason == "budget_exceeded"

    def test_diminishing_returns(self):
        t = BudgetTracker()
        for _ in range(DIMINISHING_CONSECUTIVE_LIMIT):
            t.record_turn(40, 10)
        d = check_budget(t, 100, 100000)  # used 远未超限
        assert isinstance(d, StopDecision)
        assert d.reason == "diminishing_returns"

    def test_limit_zero(self):
        t = BudgetTracker()
        assert isinstance(check_budget(t, 999, 0), ContinueDecision)


# ===== cost_tracker =====

class TestGetModelCost:
    def test_exact(self):
        assert get_model_cost("gpt-4o") == MODEL_COSTS["gpt-4o"]

    def test_prefix_longest(self):
        # glm-4-plus 是比 glm-4 更长的匹配前缀
        assert get_model_cost("glm-4-plus-xxx") == MODEL_COSTS["glm-4-plus"]

    def test_default(self):
        assert get_model_cost("") == MODEL_COSTS["default"]
        assert get_model_cost("totally-unknown") == MODEL_COSTS["default"]


class TestCalculateCost:
    def test_input_only(self):
        # gpt-4o: input 2.75 / 1M
        assert abs(calculate_cost("gpt-4o", 1_000_000, 0) - 2.75) < 1e-6

    def test_output_only(self):
        # gpt-4o: output 11.0 / 1M
        assert abs(calculate_cost("gpt-4o", 0, 1_000_000) - 11.0) < 1e-6

    def test_zero_tokens(self):
        assert calculate_cost("gpt-4o", 0, 0) == 0.0


class TestCostTracker:
    def test_accumulate_and_totals(self):
        ct = CostTracker()
        ct.accumulate("gpt-4o", 1000, 500)
        ct.accumulate("gpt-4o", 2000, 1000)
        tokens = ct.get_total_tokens()
        assert tokens["input_tokens"] == 3000
        assert tokens["output_tokens"] == 1500
        assert tokens["total_tokens"] == 4500
        assert len(ct.get_entries()) == 2
        expected = calculate_cost("gpt-4o", 1000, 500) + calculate_cost("gpt-4o", 2000, 1000)
        assert abs(ct.get_total_cost() - expected) < 1e-6

    def test_summary(self):
        ct = CostTracker()
        ct.accumulate("gpt-4o", 100, 50)
        s = ct.get_summary()
        assert s["total_calls"] == 1
        assert s["total_input_tokens"] == 100
        assert s["total_output_tokens"] == 50

    def test_reset(self):
        ct = CostTracker()
        ct.accumulate("gpt-4o", 100, 50)
        ct.reset()
        assert ct.get_total_cost() == 0.0
        assert ct.get_total_tokens()["total_tokens"] == 0
        assert len(ct.get_entries()) == 0

    def test_thread_safe(self):
        import threading
        ct = CostTracker()

        def worker():
            for _ in range(100):
                ct.accumulate("gpt-4o", 10, 5)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # 5 线程 * 100 次 = 500 次调用，无丢失
        assert len(ct.get_entries()) == 500
        assert ct.get_total_tokens()["input_tokens"] == 500 * 10
