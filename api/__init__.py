"""
API 层总入口

本目录按功能模块拆分蓝图，避免 app.py 过于臃肿。
蓝图在运行时通过 `app.register_blueprint()` 注册。
"""
from api.chart_api import chart_bp
from api.task_api import task_bp
from api.code_api import code_bp

__all__ = ["chart_bp", "task_bp", "code_bp"]
