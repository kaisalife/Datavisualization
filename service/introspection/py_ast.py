"""Python AST 静态分析工具。

主要能力：
- 提取顶层函数签名 + docstring 首行
- 提取顶层变量赋值（供 Path B 代码补全推断变量）
- 提取 import 列表
"""

from __future__ import annotations

import ast
import textwrap
from typing import Optional


def extract_function_signatures(code_str: str) -> list[dict]:
    """从代码字符串提取函数签名 + docstring 首行。

    兼容 data_preview.py 那种把真实代码包在 `code = '''...'''` 里的场景：
    先尝试剥出三引号内容。
    """
    real_code = _unwrap_triple_quoted(code_str)

    signatures = []
    try:
        tree = ast.parse(real_code)
    except SyntaxError:
        return signatures

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = [a.arg for a in node.args.args]
            doc = ast.get_docstring(node) or ""
            doc_first = doc.split("\n", 1)[0].strip() if doc else ""
            signatures.append({
                "name": node.name,
                "args": args,
                "doc": doc_first,
                "is_async": isinstance(node, ast.AsyncFunctionDef),
            })
    return signatures


def analyze_python_source(source: str) -> dict:
    """完整分析 Python 源码，返回结构化摘要。

    返回：
    {
      "imports": [{"module": "numpy", "alias": "np"}, ...],
      "functions": [{"name", "args", "doc", "is_async"}],
      "classes": [{"name", "bases", "doc"}],
      "top_level_vars": [{"name", "kind", "hint"}]
        # kind: "call" | "constant" | "unknown"
        # hint: 例如 "np.array(...)" 就记录 "np.array"
    }
    """
    result = {
        "imports": [],
        "functions": [],
        "classes": [],
        "top_level_vars": [],
    }

    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        result["parse_error"] = str(e)
        return result

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                result["imports"].append({
                    "module": alias.name,
                    "alias": alias.asname or alias.name,
                })
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                result["imports"].append({
                    "module": f"{module}.{alias.name}",
                    "alias": alias.asname or alias.name,
                })
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = [a.arg for a in node.args.args]
            doc = ast.get_docstring(node) or ""
            result["functions"].append({
                "name": node.name,
                "args": args,
                "doc": doc.split("\n", 1)[0].strip() if doc else "",
                "is_async": isinstance(node, ast.AsyncFunctionDef),
            })
        elif isinstance(node, ast.ClassDef):
            bases = [_ast_expr_to_str(b) for b in node.bases]
            doc = ast.get_docstring(node) or ""
            result["classes"].append({
                "name": node.name,
                "bases": bases,
                "doc": doc.split("\n", 1)[0].strip() if doc else "",
            })
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    result["top_level_vars"].append(_analyze_assign(target.id, node.value))
                elif isinstance(target, (ast.Tuple, ast.List)):
                    # tuple unpacking: x, y = ...
                    for elt in target.elts:
                        if isinstance(elt, ast.Name):
                            result["top_level_vars"].append(
                                _analyze_assign(elt.id, node.value)
                            )
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            result["top_level_vars"].append(
                _analyze_assign(node.target.id, node.value)
            )

    return result


# ============================================================
# 内部工具
# ============================================================

def _unwrap_triple_quoted(code_str: str) -> str:
    """如果代码是 `code = '''...'''` 结构，剥出内容。否则原样返回。"""
    m_open = code_str.find("'''")
    m_close = code_str.rfind("'''")
    if m_open != -1 and m_close > m_open:
        inner = code_str[m_open + 3:m_close]
        return textwrap.dedent(inner)
    return code_str


def _analyze_assign(name: str, value: Optional[ast.AST]) -> dict:
    """分析 `name = value` 的右侧，猜测变量类型。"""
    if value is None:
        return {"name": name, "kind": "declared", "hint": ""}
    if isinstance(value, ast.Call):
        return {"name": name, "kind": "call", "hint": _ast_expr_to_str(value.func)}
    if isinstance(value, ast.Constant):
        return {"name": name, "kind": "constant", "hint": type(value.value).__name__}
    if isinstance(value, (ast.List, ast.Tuple, ast.Dict, ast.Set)):
        return {"name": name, "kind": "literal", "hint": type(value).__name__}
    return {"name": name, "kind": "unknown", "hint": ""}


def _ast_expr_to_str(node: ast.AST) -> str:
    """把简单 AST 表达式还原成可读字符串。"""
    try:
        return ast.unparse(node)
    except Exception:
        return "<unparseable>"
