"""CSV/JSON/Parquet 文件 Reader（v4）。

直接用 pandas 读取为 DataFrame（不再经 DuckDB），返回 list[RawTable]。
pandas 自动推断类型。
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from service.data_ingestion.models import RawTable, safe_table_name


# 文件扩展名 -> 默认分隔符
_EXT_MAP = {
    ".csv": ",",
    ".tsv": "\t",
}
_DELIMITER_CANDIDATES = (",", "\t", ";", "|")
_SNIFF_LINES = 5


def _detect_delimiter(path: str, default: str) -> str:
    """按扩展名/首行内容嗅探分隔符（兼容无规范分隔符的未清洗 CSV）。"""
    try:
        with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
            lines = [ln for ln in (f.readline() for _ in range(_SNIFF_LINES)) if ln.strip()]
    except OSError:
        return default
    if not lines:
        return default
    # 若扩展名给了明确分隔符且首行能切分出多列，直接用
    if default in _DELIMITER_CANDIDATES and default in lines[0]:
        return default
    best, best_count = default, -1
    for d in _DELIMITER_CANDIDATES:
        count = max(ln.count(d) for ln in lines)
        if count > best_count:
            best, best_count = d, count
    return best


class FileReader:
    """读取 CSV/TSV/JSON/Parquet 文件，返回 list[RawTable]。"""

    @staticmethod
    def can_handle(path: str) -> bool:
        ext = Path(path).suffix.lower()
        return ext in _EXT_MAP or ext in {".json", ".jsonl", ".ndjson", ".parquet"}

    @staticmethod
    def read(
        path: str,
        table_name: str | None = None,
    ) -> list[RawTable]:
        """读取文件为 DataFrame，返回单元素 list[RawTable]。

        Args:
            path: 文件路径
            table_name: 逻辑表名 (可选，默认取文件名)

        Returns:
            list[RawTable]（含单个 RawTable）
        """
        ext = Path(path).suffix.lower()
        if not FileReader.can_handle(path):
            raise ValueError(f"FileReader 不支持 {ext} 格式")

        name = safe_table_name(table_name or Path(path).name)

        if ext in _EXT_MAP:
            sep = _detect_delimiter(path, _EXT_MAP[ext])
            df = pd.read_csv(path, sep=sep, engine="python", on_bad_lines="skip")
        elif ext in {".json", ".jsonl", ".ndjson"}:
            lines = ext != ".json" or _is_jsonl(path)
            df = pd.read_json(path, lines=lines)
        elif ext == ".parquet":
            df = pd.read_parquet(path)
        else:  # pragma: no cover
            raise ValueError(f"FileReader 不支持 {ext} 格式")

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = ["_".join(str(x) for x in c) for c in df.columns]

        return [RawTable(name=name, df=df, source_kind="file", source_path=path)]


def _is_jsonl(path: str) -> bool:
    """粗略判断 JSON 是否为 JSONL（逐行对象）。"""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            first = f.readline().lstrip()
        return first.lstrip().startswith(("{", "["))
    except OSError:
        return False