"""LLM 表格化 Reader（P2）：HTML/Markdown/日志 -> 结构化表格。

用 LLM 从非表格文本中抽取结构化数据（比 unstructured 更聪明：
能识别日志模式、嵌套数据、自由文本中的重复字段），注册为 DuckDB 表。

签名对齐现有 readers：read(db, path, table_name=None)。
LLM 默认读 .env 构造 ChatOpenAI（同步 invoke）；可注入 llm 参数便于测试
（注入对象须有 invoke(msg) -> {"content": ...} 或 AIMessage）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from service.data_ingestion.models import RawTable, safe_table_name
from service.observability import get_logger
from service.runtime.utils import extract_json_from_response

logger = get_logger(__name__)

_LLM_EXTS = {".html", ".htm", ".md", ".txt", ".log"}
_MAX_TEXT_CHARS = 20000
_MAX_ROWS = 200


def _load_env_llm():
    """从 .env 构造同步 ChatOpenAI；未配置则抛 RuntimeError。"""
    from dotenv import load_dotenv

    load_dotenv()
    import os

    base_url = os.getenv("BASE_URL", "")
    api_key = os.getenv("API_KEY", "")
    model = os.getenv("MODEL_NAME", "")
    if not all((base_url, api_key, model)):
        raise RuntimeError(".env 未配置 BASE_URL/API_KEY/MODEL_NAME，无法 LLM 表格化")
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(base_url=base_url, api_key=api_key, model=model, temperature=0)


def parse_tabular_json(content: str) -> dict | None:
    """解析 LLM 响应为 {"columns", "rows"}；无表返回 None。"""
    data = extract_json_from_response(content)
    if not isinstance(data, dict):
        return None
    columns = data.get("columns") or []
    rows = data.get("rows") or []
    if not columns or not rows:
        return None
    return {"columns": columns, "rows": rows}


def to_dataframe(data: dict) -> pd.DataFrame | None:
    """columns + rows -> DataFrame；行内列不全用 None 补齐。"""
    columns = list(data["columns"])
    rows = []
    for row in data["rows"][:_MAX_ROWS]:
        if not isinstance(row, dict):
            continue
        rows.append({c: row.get(c) for c in columns})
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=columns)
    df = df.dropna(how="all", axis=1)
    return df if not df.empty else None


class LlmTabularReader:
    """LLM 表格化 Reader。"""

    @staticmethod
    def can_handle(path: str) -> bool:
        return Path(path).suffix.lower() in _LLM_EXTS

    @staticmethod
    def read(
        path: str,
        table_name: str | None = None,
        llm=None,
        max_text_chars: int = _MAX_TEXT_CHARS,
    ) -> list[RawTable]:
        """读取非表格文本，LLM 抽取结构化表格为 DataFrame。

        Args:
            path: HTML/Markdown/日志文件路径
            table_name: 目标表名
            llm: 注入的 LLM（须有同步 invoke）；None 时读 .env 构造
            max_text_chars: 喂给 LLM 的文本截断长度

        Returns:
            list[RawTable]（含单个 RawTable）

        Raises:
            ValueError: 文件为空 / LLM 未提取到结构化数据
            RuntimeError: .env 未配置模型且未注入 llm
        """
        text = Path(path).read_text(encoding="utf-8", errors="replace")[:max_text_chars]
        if not text.strip():
            raise ValueError(f"文件为空或无法读取: {path}")

        from prompts.tabularize_prompt import get_tabularize_prompt

        llm = llm or _load_env_llm()
        prompt = get_tabularize_prompt().invoke({"text": text})
        resp = llm.invoke(prompt)
        content = resp["content"] if isinstance(resp, dict) else getattr(resp, "content", str(resp))

        data = parse_tabular_json(content)
        df = to_dataframe(data) if data else None
        if df is None:
            logger.warning("LLM 未提取到结构化数据", path=path)
            raise ValueError(f"LLM 未从文本中提取到结构化数据: {path}")

        base_name = safe_table_name(table_name or Path(path).name)
        return [RawTable(name=base_name, df=df, source_kind="document", source_path=path)]
