import asyncio
import os
import uuid
from typing import List, Optional

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)

from service.budget.token_budget import (
    BudgetTracker,
    ContinueDecision,
    StopDecision,
    check_budget,
    count_messages_tokens,
    count_tokens,
    get_context_window_for_model,
)
from service.compact.compactor import (
    estimate_messages_tokens,
    full_compact,
    microcompact_messages,
    partial_compact,
    reactive_compact_on_overflow,
)
from agent.retry import (
    LLMContextOverflowError,
    LLMError,
    QuerySource,
    with_retry,
)
from service.cost.cost_tracker import CostTracker
from service.observability.logger import (
    EVENT_BUDGET_STOP,
    EVENT_COMPACT,
    EVENT_LLM_CALL_END,
    EVENT_LLM_CALL_START,
    get_logger,
)


class QueryEngine:
    """封装一次"用户请求->多轮 LLM 调用"全过程，持有 messages 列表跨阶段共享。"""

    def __init__(self, chat_model=None, session_id: Optional[str] = None,
                 system_prompt: Optional[str] = None, model_name: str = ""):
        self.messages: List[BaseMessage] = []
        self.usage = {"input_tokens": 0, "output_tokens": 0, "calls": 0}
        self.aborted = False
        self.stop_reason: Optional[str] = None
        self.session_id = session_id or uuid.uuid4().hex
        self._chat_model = chat_model
        self._model_name = model_name
        self.budget_tracker = BudgetTracker()
        self.context_window = get_context_window_for_model(model_name)
        self.cost_tracker = CostTracker()
        self._logger = get_logger("query_engine").bind(session_id=self.session_id)
        # 单次 LLM 调用超时（秒），可用环境变量 LLM_CALL_TIMEOUT 覆盖
        self._llm_call_timeout = float(os.getenv("LLM_CALL_TIMEOUT", "60"))

        if system_prompt:
            self.messages.append(SystemMessage(content=system_prompt))

    async def run_prompt(self, prompt, chat=None,
                         query_source: str = QuerySource.GENERATE) -> str:
        """执行一次 LLM 调用，自动累积 messages 与 usage。

        prompt 可以是 dict、ChatPromptValue 或字符串。
        query_source 决定重试策略（前台重试，后台快速放弃）。
        返回 response 的文本内容。
        """
        if self.aborted:
            raise RuntimeError(f"QueryEngine {self.session_id} 已中止")

        chat = chat or self._chat_model
        if chat is None:
            raise ValueError("未提供 chat 模型，run_prompt 需要 chat_model 或 chat 参数")

        self._track_prompt_as_message(prompt)

        call_index = self.usage["calls"]
        self._logger.info(EVENT_LLM_CALL_START,
                          model=self._model_name,
                          query_source=query_source,
                          call_index=call_index,
                          messages_count=len(self.messages))

        @with_retry(query_source=query_source)
        async def _do_invoke():
            return await asyncio.wait_for(chat.ainvoke(prompt), timeout=self._llm_call_timeout)

        try:
            response = await _do_invoke()
        except LLMContextOverflowError:
            self._logger.warning(EVENT_COMPACT, trigger="context_overflow_413",
                                 messages_count=len(self.messages))
            print("⚠️ 上下文溢出 (413)，触发 reactive_compact 后重试...")
            compacted = reactive_compact_on_overflow(
                self.messages, model=self._model_name or "gpt-4o"
            )
            self._apply_compacted(compacted)

            @with_retry(query_source=query_source, max_attempts=2)
            async def _do_invoke_after_compact():
                return await asyncio.wait_for(chat.ainvoke(prompt), timeout=self._llm_call_timeout)

            response = await _do_invoke_after_compact()
        # 兼容三种返回：LangChain AIMessage(.content) / BaseAgent dict / 纯字符串
        if hasattr(response, "content"):
            content = response.content
        elif isinstance(response, dict) and "content" in response:
            content = response["content"]
        else:
            content = str(response)

        self.messages.append(AIMessage(content=content))
        self._track_usage(response)
        self.usage["calls"] += 1

        input_tokens = self.usage["input_tokens"]
        output_tokens = self.usage["output_tokens"]
        # 兜底：LangChain 未回传 usage_metadata 时用 tiktoken 估算
        if input_tokens == 0:
            input_tokens = count_messages_tokens(self.messages[:-1], self._model_name or "gpt-4o")
            self.usage["input_tokens"] = input_tokens
        if output_tokens == 0:
            output_tokens = count_tokens(content, self._model_name or "gpt-4o")
            self.usage["output_tokens"] = output_tokens

        self.budget_tracker.record_turn(
            input_tokens - self.budget_tracker.total_input_tokens,
            output_tokens - self.budget_tracker.total_output_tokens,
        )

        self.cost_tracker.accumulate(
            self._model_name or "default",
            input_tokens - self.cost_tracker.get_total_tokens()["input_tokens"],
            output_tokens - self.cost_tracker.get_total_tokens()["output_tokens"],
        )

        used = self.budget_tracker.get_total_used()
        decision = check_budget(self.budget_tracker, used, self.context_window)

        cost = self.cost_tracker.get_total_cost()
        self._logger.info(EVENT_LLM_CALL_END,
                          model=self._model_name,
                          call_index=self.usage["calls"] - 1,
                          input_tokens=input_tokens - self.budget_tracker.total_input_tokens,
                          output_tokens=output_tokens - self.budget_tracker.total_output_tokens,
                          total_tokens=used,
                          cost_rmb=cost,
                          messages_count=len(self.messages))

        if isinstance(decision, StopDecision):
            self.aborted = True
            self.stop_reason = decision.reason
            self._logger.warning(EVENT_BUDGET_STOP,
                                 reason=decision.reason,
                                 used=used,
                                 limit=self.context_window,
                                 calls=self.usage["calls"])
            print(f"⚠️ Token 预算触发停止: {decision.reason} "
                  f"(used={used}, limit={self.context_window}, "
                  f"calls={self.usage['calls']})")

        return content

    def add_message(self, message: BaseMessage):
        """手动追加一条消息。"""
        if isinstance(message, BaseMessage):
            self.messages.append(message)
        elif isinstance(message, str):
            self.messages.append(HumanMessage(content=message))
        else:
            raise TypeError(f"不支持的消息类型: {type(message)}")

    def add_ai_message(self, content: str):
        """手动追加一条 AI 消息（如 RAG 检索结果、外部计算结果）。"""
        self.messages.append(AIMessage(content=content))

    def add_human_message(self, content: str):
        """手动追加一条 Human 消息。"""
        self.messages.append(HumanMessage(content=content))

    def get_messages(self) -> List[BaseMessage]:
        """返回当前所有消息。"""
        return list(self.messages)

    def get_history_text(self, max_messages: Optional[int] = None) -> str:
        """把历史 messages 拼成文本，供下阶段引用。

        max_messages 限制取最近 N 条（不含 SystemMessage）。
        """
        msgs = [m for m in self.messages if not isinstance(m, SystemMessage)]
        if max_messages is not None:
            msgs = msgs[-max_messages:]
        parts = []
        for m in msgs:
            role = "AI" if isinstance(m, AIMessage) else "Human"
            parts.append(f"[{role}] {m.content}")
        return "\n\n".join(parts)

    def get_usage(self) -> dict:
        """返回 token 用量统计。"""
        return dict(self.usage)

    def abort(self):
        """标记中止，后续 run_prompt 将抛异常。"""
        self.aborted = True

    def reset(self):
        """清空 messages 与 usage（保留 session_id 与 context_window）。"""
        self.messages.clear()
        self.usage = {"input_tokens": 0, "output_tokens": 0, "calls": 0}
        self.aborted = False
        self.stop_reason = None
        self.budget_tracker = BudgetTracker()
        self.cost_tracker = CostTracker()

    async def compact_if_needed(self, target_ratio: float = 0.6) -> bool:
        """检查并执行压缩，三级递进：micro -> partial -> full。

        目标：把 messages token 降到 context_window * target_ratio 以下。
        返回 True 表示执行了压缩，False 表示无需压缩。
        """
        model = self._model_name or "gpt-4o"
        current_tokens = estimate_messages_tokens(self.messages, model)
        target_tokens = int(self.context_window * target_ratio)

        if current_tokens <= target_tokens:
            return False

        print(f"📦 开始压缩: 当前 {current_tokens} tokens, 目标 {target_tokens} tokens")

        compacted = microcompact_messages(self.messages, model)
        after_micro = estimate_messages_tokens(compacted, model)
        if after_micro <= target_tokens:
            self._apply_compacted(compacted)
            print(f"✅ 1级 microcompact 完成: {current_tokens} -> {after_micro} tokens")
            return True

        chat = self._chat_model
        if chat is not None:
            try:
                compacted = await partial_compact(compacted, chat, keep_last_n=6, model=model)
                after_partial = estimate_messages_tokens(compacted, model)
                if after_partial <= target_tokens:
                    self._apply_compacted(compacted)
                    print(f"✅ 2级 partial_compact 完成: {current_tokens} -> {after_partial} tokens")
                    return True
            except Exception as e:
                print(f"⚠️ 2级 partial_compact 失败: {e}")

            try:
                compacted = await full_compact(self.messages, chat, model=model)
                after_full = estimate_messages_tokens(compacted, model)
                self._apply_compacted(compacted)
                print(f"✅ 3级 full_compact 完成: {current_tokens} -> {after_full} tokens")
                return True
            except Exception as e:
                print(f"⚠️ 3级 full_compact 失败: {e}")

        self._apply_compacted(compacted)
        after = estimate_messages_tokens(compacted, model)
        print(f"📦 压缩结束: {current_tokens} -> {after} tokens")
        return True

    def _apply_compacted(self, compacted: List[BaseMessage]):
        """应用压缩后的 messages，重置 budget 状态。"""
        self.messages = compacted
        self.aborted = False
        self.stop_reason = None
        self.budget_tracker = BudgetTracker()
        self.usage = {"input_tokens": 0, "output_tokens": 0, "calls": self.usage["calls"]}

    def _track_prompt_as_message(self, prompt):
        """把 prompt 转为 HumanMessage 追加到 messages。"""
        if isinstance(prompt, str):
            self.messages.append(HumanMessage(content=prompt))
            return
        if isinstance(prompt, dict):
            text = "\n".join(str(v) for v in prompt.values() if v is not None)
            self.messages.append(HumanMessage(content=text))
            return
        to_messages = getattr(prompt, "to_messages", None)
        if callable(to_messages):
            try:
                for m in to_messages():
                    self.messages.append(m)
                return
            except Exception:
                pass
        self.messages.append(HumanMessage(content=str(prompt)))

    def _track_usage(self, response):
        """从 response.response_metadata 提取 token 用量。"""
        meta = getattr(response, "response_metadata", None) or {}
        token_usage = meta.get("token_usage") or meta.get("usage") or {}
        self.usage["input_tokens"] += int(token_usage.get("prompt_tokens", 0))
        self.usage["output_tokens"] += int(token_usage.get("completion_tokens", 0))

    def __len__(self):
        return len(self.messages)

    def __repr__(self):
        used = self.budget_tracker.get_total_used()
        cost = self.cost_tracker.get_total_cost()
        return (f"QueryEngine(session_id={self.session_id[:8]}..., "
                f"messages={len(self.messages)}, calls={self.usage['calls']}, "
                f"tokens={used}/{self.context_window}, cost=¥{cost:.4f}, "
                f"aborted={self.aborted}, stop_reason={self.stop_reason})")
