from langchain_openai import ChatOpenAI
from typing import Any, Dict, List, Optional
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_core.runnables import Runnable, RunnableConfig
from langchain_core.prompts import ChatPromptTemplate

class BaseAgent(Runnable):
    def __init__(self,
                 model_name: str,
                 model_url: str,
                 model_key: str,
                 mcp_config: dict,
                 verbose: bool = False
    ):
        self.model_name = model_name
        self.model_url = model_url
        self.model_key = model_key
        self.mcp_config = mcp_config
        self.verbose = verbose
        self.client: Optional[MultiServerMCPClient] = None
        self.tools: Optional[List] = None
        self.signature = f"{model_name}@{model_url[:20]}..."

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

