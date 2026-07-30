from pydantic import BaseModel
from typing import Any, Dict, List, Optional


class GenerateChartWithPromptRequest(BaseModel):
    """生成图表请求模型"""
    file_paths: Optional[List[str]] = None  # 文件路径（CSV/Excel/Parquet），可选
    db_config: Optional[Dict[str, Any]] = None  # 数据库连接配置，可选
    user_prompt: str  # 用户提示词
    config: Optional[str] = None  # 图表配置（JSON字符串）
    model_url: Optional[str] = None  # 模型URL
    model_type: Optional[str] = None  # 模型类型
    model_api_key: Optional[str] = None  # 模型API密钥
    api_key: Optional[str] = None  # 认证API密钥
    mcp_prompt: Optional[str] = ""  # MCP提示词
    skill_prompt: Optional[str] = ""  # 技能提示词
    viz_mode: Optional[str] = "auto"  # "auto" | "chart" | "scientific"


class CompleteVizCodeRequest(BaseModel):
    """Path B：代码可视化补全请求。"""
    code_file_paths: List[str]                    # 用户代码文件路径列表
    user_prompt: str                              # 可视化需求描述
    scientific_lib: Optional[str] = None          # "matplotlib" | "plotly" | "seaborn" | "auto"
    model_url: Optional[str] = None
    model_type: Optional[str] = None
    model_api_key: Optional[str] = None
    api_key: Optional[str] = None                 # 认证 API 密钥


class GenerateChartWithPromptResponse(BaseModel):
    """生成图表响应模型"""
    Charts: List[str]  # 图表类型列表
    HtmlFilePaths: List[str]  # HTML文件路径列表
    AgentLogs: List[str]  # 代理日志列表


class GetChartRequest(BaseModel):
    """获取图表请求模型"""
    chartId: str  # 图表ID


class ErrorResponse(BaseModel):
    """错误响应模型"""
    detail: str  # 错误详情
