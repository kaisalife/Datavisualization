"""CSV/JSON/Parquet 文件 Reader（v4）。

直接用 pandas 读取为 DataFrame（不再经 DuckDB），返回 list[RawTable]。
pandas 自动推断类型。

编码：Windows 上 Excel 导出的 CSV 默认是 GBK/GB18030，直接按 UTF-8 读会抛
``UnicodeDecodeError``。这里先探测 BOM / UTF-8 / GB18030 / UTF-16，再交给 pandas。
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from service.data_ingestion.limits import (
    effective_row_limit,
    enforce_ingest_limits,
    ingest_limits,
)
from service.data_ingestion.models import RawTable, safe_table_name
from service.runtime.utils import display_name_from_path


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


def _count_unquoted(line: str, delimiter: str) -> int:
    """统计一行中不在双引号内的分隔符数量（支持 "" 转义）。"""
    count = 0
    in_quotes = False
    index = 0
    while index < len(line):
        char = line[index]
        if char == '"':
            if in_quotes and index + 1 < len(line) and line[index + 1] == '"':
                index += 2
                continue
            in_quotes = not in_quotes
        elif char == delimiter and not in_quotes:
            count += 1
        index += 1
    return count


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

    # 按「引号外出现次数」判断，避免把 "说明,含逗号" 里的逗号当成列分隔符
    stats: dict[str, tuple[int, int]] = {}
    for delimiter in _DELIMITER_CANDIDATES:
        counts = [_count_unquoted(line, delimiter) for line in lines]
        counts = [count for count in counts if count > 0]
        if not counts:
            continue
        mode = max(set(counts), key=counts.count)
        stats[delimiter] = (counts.count(mode), mode)

    if not stats:
        return default
    # 扩展名给出的分隔符只要确实出现过，就优先
    if default in stats:
        return default
    return max(stats, key=lambda d: stats[d])


def _read_csv_guarded(
    path: str, *, sep: str, encoding: str, source: str
) -> pd.DataFrame:
    """带行数/单元格上限的 CSV 读取。

    先只读表头拿列数，再按 ``nrows=上限+1`` 读；超过上限直接抛
    ``DataTooLargeError``，**不做静默截断**（截断会改变聚合口径）。
    """
    max_rows, max_cells = ingest_limits()
    read_kwargs = {
        "sep": sep,
        "engine": "python",
        "on_bad_lines": "skip",
        "encoding": encoding,
    }
    if not max_rows and not max_cells:
        return pd.read_csv(path, **read_kwargs)

    columns = 1
    try:
        header = pd.read_csv(path, nrows=0, **read_kwargs)
        columns = max(1, len(header.columns))
    except Exception:
        # 表头都读不出来时交给正常读取抛原始错误；行数上限仍会生效
        columns = 1

    effective_rows = effective_row_limit(columns)
    if effective_rows <= 0:  # pragma: no cover - 两个上限都为 0 时上面已返回
        return pd.read_csv(path, **read_kwargs)

    df = pd.read_csv(path, nrows=effective_rows + 1, **read_kwargs)
    if len(df) > effective_rows:
        enforce_ingest_limits(
            effective_rows + 1,
            columns,
            source,
            rows_are_lower_bound=True,
        )
    return df


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
            df = _read_csv_guarded(
                path,
                sep=sep,
                encoding=encoding,
                source=display_name_from_path(path),
            )
        elif ext in {".json", ".jsonl", ".ndjson"}:
            df = _read_json(path, lines=ext != ".json" or _is_jsonl(path))
        elif ext == ".parquet":
            df = pd.read_parquet(path)
        else:  # pragma: no cover
            raise ValueError(f"FileReader 不支持 {ext} 格式")

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = ["_".join(str(x) for x in c) for c in df.columns]

        return [RawTable(name=name, df=df, source_kind="file", source_path=path)]


def _read_text(path: str) -> str:
    """按探测到的编码读取文本（JSON/JSONL 共用）。"""
    encoding = _detect_encoding(path)
    try:
        return Path(path).read_text(encoding=encoding)
    except UnicodeDecodeError:
        # 探测将来可能遇到混合编码文件，替换非法字节比直接失败更有用
        return Path(path).read_text(encoding=encoding, errors="replace")


def _is_jsonl(path: str) -> bool:
    """判断 .json 文件是否实际是逐行 JSON（JSONL/NDJSON）。

    先尝试把整个文件当成一个 JSON 文档；能解析就**不是** JSONL。
    只有整体解析失败、且首个非空行本身是 JSON 对象/数组时，才按 JSONL 读取。
    这样既不会把格式化过的 JSON 数组误判成 JSONL，也能兼容扩展名写错的
    多行对象文件。
    """
    try:
        text = _read_text(path)
    except OSError:
        return False
    stripped = text.strip()
    if not stripped:
        return False
    try:
        json.loads(stripped)
        return False
    except json.JSONDecodeError:
        pass

    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if not first:
        return False
    try:
        value = json.loads(first)
    except json.JSONDecodeError:
        return False
    return isinstance(value, (dict, list))


def _records_to_frame(records: list) -> pd.DataFrame:
    """记录列表 -> DataFrame；对象记录用 json_normalize 展开嵌套字段。"""
    if not records:
        return pd.DataFrame()
    if all(isinstance(item, dict) for item in records):
        return pd.json_normalize(records)
    try:
        return pd.DataFrame(records)
    except ValueError:
        # 标量/嵌套混合时退化为单列，避免整份数据读不出来
        return pd.DataFrame({"value": records})


def json_to_frame(data) -> pd.DataFrame:
    """JSON 值 -> DataFrame（数组、单对象、列数组、嵌套对象都兼容）。

    文件 Reader 与 API Reader 共用；嵌套对象展开成 ``指标.销售额`` 这类点号列。
    """
    if isinstance(data, list):
        return _records_to_frame(data)
    if isinstance(data, dict):
        values = list(data.values())
        # 顶层是「列名 -> 数组」的宽表形态，按列构造
        if values and all(isinstance(v, (list, tuple)) for v in values):
            try:
                return pd.DataFrame(data)
            except ValueError:
                pass
        # 单条记录（含嵌套对象）包一层，交给 json_normalize 展开
        return _records_to_frame([data])
    return pd.DataFrame({"value": [data]})


def _read_json_document(path: str) -> pd.DataFrame:
    """读取单个 JSON 文档（对象或数组）。"""
    text = _read_text(path)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 解析失败: {Path(path).name}: {exc}") from exc
    return json_to_frame(data)


def _read_json_lines(path: str) -> pd.DataFrame:
    """读取 JSONL/NDJSON：一行一个 JSON 对象（空行忽略）。"""
    text = _read_text(path)
    records: list = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"JSONL 解析失败: {Path(path).name} 第 {line_no} 行: {exc}"
            ) from exc
    return _records_to_frame(records)


def _read_json(path: str, lines: bool) -> pd.DataFrame:
    """读取 JSON/JSONL，兼容单对象、数组、列数组与嵌套字段。"""
    return _read_json_lines(path) if lines else _read_json_document(path)