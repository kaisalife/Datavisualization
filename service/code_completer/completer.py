"""代码可视化补全核心逻辑。

流程：
1. 校验代码文件路径（防止越权访问）
2. AST 静态分析（复用 service.introspection.py_ast）
3. 调 LLM 生成可视化片段
4. 拼装完整脚本返回（不执行）
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from service.introspection.py_ast import analyze_python_source


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class CodeCompletionError(Exception):
    """代码补全流程错误。"""


# 允许读取的目录白名单（可通过 env 扩展）
_DEFAULT_ALLOWED_ROOTS = [
    PROJECT_ROOT / "test_env",
    PROJECT_ROOT / "temp_uploads",
    PROJECT_ROOT / "user_code",
]


def _allowed_roots() -> list[Path]:
    """允许读取的根目录列表。CODE_COMPLETER_ALLOWED_ROOTS 可追加（分号分隔）。"""
    roots = list(_DEFAULT_ALLOWED_ROOTS)
    extra = os.getenv("CODE_COMPLETER_ALLOWED_ROOTS", "")
    if extra:
        for p in extra.split(os.pathsep):
            if p.strip():
                roots.append(Path(p.strip()))
    return roots


def _validate_path(code_path: str) -> Path:
    """校验路径必须在白名单目录下，防止越权访问。"""
    path = Path(code_path).resolve()
    if not path.exists() or not path.is_file():
        raise CodeCompletionError(f"文件不存在或不是文件: {code_path}")
    if path.suffix.lower() != ".py":
        raise CodeCompletionError(f"仅支持 .py 文件: {code_path}")

    for root in _allowed_roots():
        try:
            path.relative_to(root.resolve())
            return path
        except ValueError:
            continue
    raise CodeCompletionError(
        f"路径不在允许目录内: {code_path}. "
        f"允许的根目录: {[str(r) for r in _allowed_roots()]}"
    )


def _extract_completion_json(response_text: str) -> dict:
    """从 LLM 响应中提取 JSON。

    响应可能是纯 JSON 或包裹在 ```json ... ``` 中。
    """
    from service.utils import extract_json_from_response

    parsed = extract_json_from_response(response_text)
    if not parsed:
        raise CodeCompletionError(f"LLM 响应无法解析为 JSON: {response_text[:500]}")

    required = ("snippet", "explanation")
    for key in required:
        if key not in parsed:
            raise CodeCompletionError(f"LLM 响应缺少字段 {key}: {parsed}")

    parsed.setdefault("libs", [])
    return parsed


async def complete_visualization_code(request: Any) -> dict:
    """补全可视化代码的主入口。

    request 需要有属性：code_file_paths / user_prompt / scientific_lib / model_url / model_type / model_api_key
    返回结构：
    {
        "status": "success",
        "results": [{
            "source_file": "...",
            "completed_code": "...",
            "inserted_snippet": "...",
            "insertion_point": {"line": N, "position": "end_of_file"},
            "explanation": "...",
            "recommended_libs": ["matplotlib"]
        }]
    }
    """
    code_paths = getattr(request, "code_file_paths", None) or []
    if not code_paths:
        raise CodeCompletionError("code_file_paths 不能为空")

    user_prompt = getattr(request, "user_prompt", "") or ""
    scientific_lib = getattr(request, "scientific_lib", None) or "auto"

    # 延迟导入避免循环依赖
    from service.config import load_config, get_agent_class
    from service.query_engine import QueryEngine
    from prompts.agent_prompt import get_agent_viz_code_completion_prompt

    config = load_config(None)
    chat = get_agent_class(
        agent_class=config["agent_class"],
        model_url=getattr(request, "model_url", None) or config.get("model_url"),
        model_type=getattr(request, "model_type", None) or config.get("model_type"),
        model_api_key=getattr(request, "model_api_key", None) or config.get("model_api_key"),
        mcp_config=config.get("mcp_config") or {},
    )
    await chat.initialize()
    engine = QueryEngine(chat_model=chat, model_name=getattr(request, "model_type", None))
    prompt_template = get_agent_viz_code_completion_prompt()

    results = []
    for code_path in code_paths:
        validated = _validate_path(code_path)
        source = validated.read_text(encoding="utf-8")

        # AST 摘要
        summary = analyze_python_source(source)
        summary_text = json.dumps(summary, ensure_ascii=False, indent=2)

        # LLM 生成片段
        response_text = await engine.run_prompt(prompt_template.invoke({
            "source_summary": summary_text,
            "full_source": source,
            "user_prompt": user_prompt,
            "scientific_lib": scientific_lib,
        }))

        completion = _extract_completion_json(response_text)

        snippet = completion["snippet"]
        # 拼装完整脚本
        completed_code = source.rstrip() + "\n\n# --- 追加的可视化代码 ---\n" + snippet
        line_count = len(source.splitlines())

        results.append({
            "source_file": str(validated),
            "completed_code": completed_code,
            "inserted_snippet": snippet,
            "insertion_point": {"line": line_count + 2, "position": "end_of_file"},
            "explanation": completion["explanation"],
            "recommended_libs": completion.get("libs", []),
        })

    return {"status": "success", "results": results}
