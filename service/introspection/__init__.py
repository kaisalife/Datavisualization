"""introspection 包：AST 分析工具。

供 code_completer 和其他模块复用。
"""

from service.introspection.py_ast import extract_function_signatures, analyze_python_source

__all__ = [
    "extract_function_signatures",
    "analyze_python_source",
]
