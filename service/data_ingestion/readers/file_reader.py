"""CSV/JSON/Parquet 文件 Reader（v4）。

直接用 pandas 读取为 DataFrame（不再经 DuckDB），返回 list[RawTable]。
pandas 自动推断类型。

编码：Windows 上 Excel 导出的 CSV 默认是 GBK/GB18030，直接按 UTF-8 读会抛
``UnicodeDecodeError``。这里先探测 BOM / UTF-8 / GB18030 / UTF-16，再交给 pandas。
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
_ENCODING_SNIFF_BYTES = 64 * 1024


def _detect_encoding(path: str) -> str:
    """探测文本编码，返回 pandas/open 可用的编码名。

    顺序：BOM -> UTF-8 -> GB18030（兼容 GBK/GB2312）-> UTF-8 兜底。
    UTF-8 探测允许头部截断最后一个多字节字符（只读 64KB）。
    """
    try:
        with open(path, "rb") as f:
            head = f.read(_ENCODING_SNIFF_BYTES)
    except OSError:
        return "utf-8"

    if head.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16"
    # 无 BOM 的 UTF-16：ASCII 字符高位是 0，按奇偶字节里的 \x00 判断端序
    if head and head.count(b"\x00") > len(head) * 0.1:
        even_nuls = head[0::2].count(b"\x00")
        odd_nuls = head[1::2].count(b"\x00")
        return "utf-16-le" if odd_nuls >= even_nuls else "utf-16-be"

    for encoding in ("utf-8", "gb18030"):
        try:
            head.decode(encoding)
        except UnicodeDecodeError as exc:
            # 头部正好截断一个多字节字符，不算编码失败
            if exc.start >= len(head) - 4:
                return encoding
            continue
        return encoding
    return "utf-8"


def _detect_delimiter(path: str, default: str, encoding: str | None = None) -> str:
    """按扩展名/首行内容嗅探分隔符（兼容无规范分隔符的未清洗 CSV）。"""
    try:
        with open(
            path,
            "r",
            encoding=encoding or _detect_encoding(path),
            errors="replace",
            newline="",
        ) as f:
            lines = [ln for ln in (f.readline() for _ in range(_SNIFF_LINES)) if ln.strip()]
    except (OSError, UnicodeError):
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
            encoding = _detect_encoding(path)
            sep = _detect_delimiter(path, _EXT_MAP[ext], encoding=encoding)
            df = pd.read_csv(
                path,
                sep=sep,
                engine="python",
                on_bad_lines="skip",
                encoding=encoding,
            )
        elif ext in {".json", ".jsonl", ".ndjson"}:
            lines = ext != ".json" or _is_jsonl(path)
            df = pd.read_json(path, lines=lines, encoding=_detect_encoding(path))
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