"""introspection 包：AST + DataFrame 语义推断工具。

供 viz_data Adapter 和未来的 code_completer 复用。
"""

from service.introspection.py_ast import extract_function_signatures, analyze_python_source
from service.introspection.df_stats import (
    infer_column_schema,
    infer_semantic_hints,
    dataframe_to_column_schemas,
)

__all__ = [
    "extract_function_signatures",
    "analyze_python_source",
    "infer_column_schema",
    "infer_semantic_hints",
    "dataframe_to_column_schemas",
]
