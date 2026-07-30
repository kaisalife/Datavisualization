"""自定义异常层级。

统一错误处理：用异常替代进程退出，由 Flask 全局中间件 catch。
"""


class ServiceError(Exception):
    """服务层基础异常。"""
    pass


class ConfigError(ServiceError):
    """配置错误（文件不存在/JSON格式错误/加载失败）。"""
    pass


class AgentInitError(ServiceError):
    """Agent 初始化失败。"""
    pass


class DataPreviewError(ServiceError):
    """数据预览失败。"""
    pass


class ChartGenerationError(ServiceError):
    """图表生成失败。"""
    pass
