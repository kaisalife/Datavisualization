import asyncio

from langchain_openai import ChatOpenAI
from typing import Any, Callable, Dict, List, Optional
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_core.runnables import Runnable, RunnableConfig
from langchain_core.prompts import ChatPromptTemplate

from service.monitoring import trace
from service.observability import get_logger
from service.runtime.utils import get_env_int, get_llm_extra_headers

logger = get_logger(__name__)

class BaseAgent(Runnable):
    def __init__(self,
                 model_name: str,
                 model_url: str,
                 model_key: str,
                 mcp_config: dict,
                 verbose: bool = False
    ):
        self.model_name = model_name or ""
        self.model_url = model_url or ""
        self.model_key = model_key or ""
        self.mcp_config = mcp_config or {}
        self.verbose = verbose
        self.client: Optional[MultiServerMCPClient] = None
        self.tools: Optional[List] = None
        self._mcp_lock: Optional[asyncio.Lock] = None
        self.task_id: str = ""
        self.total_usage: Dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "calls": 0}
        self.signature = f"{self.model_name}@{self.model_url[:20]}..." if self.model_url else f"{self.model_name}@(no url)"

    @trace(category="init")
    async def initialize(self) -> None:
        """初始化 LLM；MCP 工具按需加载。

        核心 plan/chart/debug 路径都显式传入本地工具池，不需要 MCP；
        而 MCP 工具发现会启动 stdio 子进程（实测约 4.4s），因此推迟到
        ``arun_with_tools`` 未显式传 tools 时再加载。
        """
        logger.info("agent_init_start", signature=self.signature)

        # Validate OpenAI configuration
        if not self.model_key:
            raise ValueError(
                "❌ Model API key not provided. Please provide your model key."
            )
        if not self.model_url:
            logger.warning("agent_model_url_missing", model=self.model_name)

        # 每次初始化都重置 MCP 状态，避免复用 agent 时拿到上一轮的旧工具。
        self.client = None
        self.tools = None

        try:
            self.chat = ChatOpenAI(
                model_name=self.model_name,
                base_url=self.model_url,
                api_key=self.model_key,
                timeout=get_env_int("AGENT_TIMEOUT", 120),
                max_retries=3,
                max_tokens=get_env_int("AGENT_MAX_TOKENS", 8192),
                default_headers=get_llm_extra_headers() or None,
            )
        except Exception as e:
            raise RuntimeError(f"❌ Failed to initialize AI model: {e}")
        logger.info("agent_init_done", model=self.model_name, signature=self.signature)

    async def _ensure_mcp_tools(self) -> List:
        """按需加载 MCP 工具（无 MCP 配置时返回空列表）。

        Returns:
            MCP 工具列表；加载失败抛 RuntimeError，保持与旧 initialize 一致
            的错误语义，但只在真正需要 MCP 工具时发生。
        """
        if self.tools is not None:
            return self.tools
        if not self.mcp_config:
            self.tools = []
            return self.tools

        if self._mcp_lock is None:
            self._mcp_lock = asyncio.Lock()
        async with self._mcp_lock:
            if self.tools is not None:
                return self.tools
            try:
                self.client = MultiServerMCPClient(self.mcp_config)
                self.tools = await self.client.get_tools()
            except Exception as e:
                raise RuntimeError(
                    f"❌ Failed to initialize MCP client: {e}\n"
                    f"   Please ensure MCP services are running at the configured ports.\n"
                    f"   Run: python agent_tools/start_mcp_services.py"
                ) from e

            if not self.tools:
                logger.warning("mcp_tools_empty", mcp_config=self.mcp_config)
            else:
                logger.info("mcp_tools_loaded", count=len(self.tools))
                if self.verbose:
                    try:
                        tool_names = []
                        for t in self.tools:
                            name = getattr(t, "name", None) or getattr(t, "__name__", "<unknown>")
                            tool_names.append(name)
                        logger.info("mcp_tool_names", tools=tool_names)
                    except Exception:
                        pass
        return self.tools

    def _track_usage(self, response) -> None:
        """提取 LLM 响应的 usage_metadata，累加并推送 token 事件到前端。"""
        try:
            usage_meta = getattr(response, "usage_metadata", None) or {}
            prompt_tokens = int(usage_meta.get("input_tokens", 0))
            completion_tokens = int(usage_meta.get("output_tokens", 0))
            if prompt_tokens == 0 and completion_tokens == 0:
                return
            self.total_usage["prompt_tokens"] += prompt_tokens
            self.total_usage["completion_tokens"] += completion_tokens
            self.total_usage["calls"] += 1
            self.total_usage["total_tokens"] = self.total_usage["prompt_tokens"] + self.total_usage["completion_tokens"]
            if self.task_id:
                from service.monitoring.ws_streamer import ws_streamer
                from service.monitoring.trace_store import trace_store as _ts
                from datetime import datetime, timezone
                _ts.add_tokens(self.task_id, {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                    "model_name": self.model_name,
                    "func_name": "ainvoke",
                })
                ws_streamer.broadcast(self.task_id, {
                    "type": "token",
                    "task_id": self.task_id,
                    "model_name": self.model_name,
                    "func_name": "ainvoke",
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                    "cumulative_total": self.total_usage["total_tokens"],
                    "call_index": self.total_usage["calls"] - 1,
                    "cost_rmb": 0,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
        except Exception:
            pass

    @trace(category="llm_call")
    async def ainvoke(
        self, 
        input: Any, 
        config: Optional[RunnableConfig] = None
    ) -> Dict[str, Any]:
        """
        异步调用代理
        
        Args:
            input: 输入字典或ChatPromptValue，包含user_prompt等字段
            config: 可选的运行时配置
            
        Returns:
            代理的响应结果
        """
        if self.chat is None:
            raise RuntimeError("Agent not initialized. Call initialize() first.")
        
        # 处理输入 - 支持字典和ChatPromptValue两种格式
        if hasattr(input, 'to_messages'):
            # 如果是ChatPromptValue，直接使用
            messages = input.to_messages()
            # 尝试从消息中提取user_prompt用于日志
            user_prompt = ""
            for msg in messages:
                if hasattr(msg, 'type') and msg.type == 'human':
                    user_prompt = msg.content
                    break
        else:
            # 如果是字典格式
            user_prompt = input.get("user_prompt", "")
            # 使用chat模型生成响应
            messages = [
                ("system", "You are a helpful data visualization assistant."),
                ("user", user_prompt)
            ]
        
        response = await self.chat.ainvoke(messages)
        self._track_usage(response)

        return {
            "content": response.content,
            "agent_logs": [f"Processed user prompt: {user_prompt[:50]}..."]
        }

    def _to_messages(self, input: Any) -> list:
        """把输入统一转为 LangChain 消息列表。"""
        if hasattr(input, "to_messages"):
            return input.to_messages()
        if isinstance(input, dict):
            if "user_prompt" in input:
                return [
                    ("system", "You are a helpful data visualization assistant."),
                    ("user", input["user_prompt"]),
                ]
            return [input]
        if isinstance(input, str):
            return [("user", input)]
        return input

    @trace(category="llm_call")
    async def arun_with_tools(
        self,
        input: Any,
        max_iterations: int = 10,
        config: Optional[RunnableConfig] = None,
        tools: Optional[List] = None,
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        """工具调用循环（agent loop）。

        LLM 自主决定是否调用工具：每轮若返回 tool_calls 则执行对应工具并把结果
        作为 ToolMessage 喂回，直到 LLM 不再调用工具给出最终回答，或达到
        max_iterations 强制停止。

        与 ainvoke 的区别：ainvoke 是单次 LLM 调用（供 QueryEngine 固定流水线使用）；
        arun_with_tools 让 LLM 自主编排工具，适用于需要 Agent 自主决策的场景。

        Args:
            input: ChatPromptValue / dict / str / 消息列表
            max_iterations: 最大工具调用轮次，防止无限循环
            config: 可选运行时配置
            tools: 可选工具列表（LangChain BaseTool）。显式传入时直接使用（核心路径
                都传本地工具池，不会加载 MCP）；为 None 时按需加载 MCP 工具。
            should_stop: 每轮工具执行完后调用的提前结束判定。返回 True 时不再发起
                下一轮 LLM 调用，直接返回当前 content 与日志（供 plan 达到目标数时使用）。

        Returns:
            {"content": 最终回答, "agent_logs": [...], "tool_calls": [...]}
        """
        from langchain_core.messages import ToolMessage

        if self.chat is None:
            raise RuntimeError("Agent not initialized. Call initialize() first.")
        use_tools = tools if tools is not None else await self._ensure_mcp_tools()
        if not use_tools:
            # 无工具可用，降级为普通单次调用
            return await self.ainvoke(input, config)

        chat_with_tools = self.chat.bind_tools(use_tools)
        messages = self._to_messages(input)

        agent_logs: List[str] = []
        tool_calls_log: List[Dict[str, Any]] = []
        content = ""

        for i in range(max_iterations):
            response = await chat_with_tools.ainvoke(messages)
            self._track_usage(response)
            content = response.content if hasattr(response, "content") else str(response)
            messages.append(response)

            tool_calls = getattr(response, "tool_calls", None) or []
            if not tool_calls:
                agent_logs.append(f"✅ 第 {i + 1} 轮：LLM 给出最终回答（无工具调用）")
                return {"content": content, "agent_logs": agent_logs, "tool_calls": tool_calls_log}

            for tc in tool_calls:
                if isinstance(tc, dict):
                    tool_name = tc.get("name", "")
                    tool_args = tc.get("args", {})
                    tool_id = tc.get("id", "")
                else:
                    tool_name = getattr(tc, "name", "")
                    tool_args = getattr(tc, "args", {})
                    tool_id = getattr(tc, "id", "")
                agent_logs.append(f"🔧 第 {i + 1} 轮：调用工具 {tool_name}({tool_args})")
                tool_calls_log.append({"iteration": i + 1, "name": tool_name, "args": tool_args})

                tool_found = None
                for t in use_tools:
                    t_name = getattr(t, "name", None) or getattr(t, "__name__", "")
                    if t_name == tool_name:
                        tool_found = t
                        break
                if tool_found is None:
                    tool_result = f"Error: tool '{tool_name}' not found"
                else:
                    try:
                        result = await tool_found.ainvoke(tool_args)
                        tool_result = result if isinstance(result, str) else str(result)
                    except Exception as e:
                        tool_result = f"Error executing {tool_name}: {e}"
                agent_logs.append(f"   -> {tool_result[:200]}")
                messages.append(ToolMessage(content=tool_result, tool_call_id=tool_id or tool_name))

            if should_stop is not None:
                try:
                    if should_stop():
                        agent_logs.append("🎯 已满足目标，提前结束工具循环")
                        return {
                            "content": content,
                            "agent_logs": agent_logs,
                            "tool_calls": tool_calls_log,
                        }
                except Exception as e:
                    # 判定回调是优化项，异常不应影响主流程，只记录后继续。
                    agent_logs.append(f"⚠️ should_stop 判定异常，继续执行: {e}")

        agent_logs.append(f"⚠️ 达到最大轮次 {max_iterations}，强制停止")
        return {"content": content, "agent_logs": agent_logs, "tool_calls": tool_calls_log}

    def invoke(
        self, 
        input: Any, 
        config: Optional[RunnableConfig] = None
    ) -> Dict[str, Any]:
        """
        同步调用代理
        
        Args:
            input: 输入字典或ChatPromptValue，包含user_prompt等字段
            config: 可选的运行时配置
            
        Returns:
            代理的响应结果
        """
        import asyncio
        return asyncio.run(self.ainvoke(input, config))

