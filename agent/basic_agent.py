from langchain_openai import ChatOpenAI
from typing import Any, Dict, List, Optional
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_core.runnables import Runnable, RunnableConfig
from langchain_core.prompts import ChatPromptTemplate

from service.monitoring import trace

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
        self.signature = f"{self.model_name}@{self.model_url[:20]}..." if self.model_url else f"{self.model_name}@(no url)"

    @trace(category="init")
    async def initialize(self) -> None:
        """Initialize MCP client and AI model"""
        print(f"🚀 Initializing agent: {self.signature}")

        # Validate OpenAI configuration
        if not self.model_key:
            raise ValueError(
                "❌ Model API key not provided. Please provide your model key."
            )
        if not self.model_url:
            print("⚠️  model URL not set")

        try:
            # Create MCP client
            self.client = MultiServerMCPClient(self.mcp_config)

            # Get tools
            self.tools = await self.client.get_tools()
            if not self.tools:
                print("⚠️  Warning: No MCP tools loaded. MCP services may not be running.")
                print(f"   MCP configuration: {self.mcp_config}")
            else:
                print(f"✅ Loaded {len(self.tools)} MCP tools")
                if self.verbose:
                    try:
                        tool_names = []
                        for t in self.tools:
                            name = getattr(t, "name", None) or getattr(t, "__name__", "<unknown>")
                            tool_names.append(name)
                        print(f"🔧 Tools: {', '.join(tool_names)}")
                    except Exception:
                        pass
        except Exception as e:
            raise RuntimeError(
                f"❌ Failed to initialize MCP client: {e}\n"
                f"   Please ensure MCP services are running at the configured ports.\n"
                f"   Run: python agent_tools/start_mcp_services.py"
            )

        try:
            self.chat= ChatOpenAI(model_name=self.model_name,
                                         base_url=self.model_url,
                                        api_key=self.model_key)
        except Exception as e:
            raise RuntimeError(f"❌ Failed to initialize AI model: {e}")
        print(f"✅ Agent {self.model_name} initialization completed")

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
    ) -> Dict[str, Any]:
        """工具调用循环（agent loop）。

        LLM 自主决定是否调用已加载的 MCP 工具：每轮若返回 tool_calls 则执行
        对应工具并把结果作为 ToolMessage 喂回，直到 LLM 不再调用工具给出最终回答，
        或达到 max_iterations 强制停止。

        与 ainvoke 的区别：ainvoke 是单次 LLM 调用（供 QueryEngine 固定流水线使用）；
        arun_with_tools 让 LLM 自主编排工具，适用于需要 Agent 自主决策的场景。

        Args:
            input: ChatPromptValue / dict / str / 消息列表
            max_iterations: 最大工具调用轮次，防止无限循环
            config: 可选运行时配置

        Returns:
            {"content": 最终回答, "agent_logs": [...], "tool_calls": [...]}
        """
        from langchain_core.messages import ToolMessage

        if self.chat is None:
            raise RuntimeError("Agent not initialized. Call initialize() first.")
        if not self.tools:
            # 无工具可用，降级为普通单次调用
            return await self.ainvoke(input, config)

        chat_with_tools = self.chat.bind_tools(self.tools)
        messages = self._to_messages(input)

        agent_logs: List[str] = []
        tool_calls_log: List[Dict[str, Any]] = []
        content = ""

        for i in range(max_iterations):
            response = await chat_with_tools.ainvoke(messages)
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
                for t in self.tools:
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

