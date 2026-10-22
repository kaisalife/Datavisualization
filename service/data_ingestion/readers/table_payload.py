"""把模型返回的原始文本解析成表格载荷（columns + rows）。

为什么需要这一层：视觉模型（尤其非 OpenAI 厂商）经常无视「只输出严格 JSON」：
会返回 Markdown 表格、HTML ``<table>``、JSON 外面包一层 ``{"data": ...}``，
或者把表放在数组/嵌套键里。只认 JSON 会把整张表丢掉，用户看到的是
「未从图片中提取到结构化表格」，与模型实际能力不符。

输出统一为::

    [{"title": "可选", "columns": [...], "rows": [{列名: 值, ...}, ...]}]

调用方（``MultimodalReader`` / ``OfficeImageReader``）再走原有的
``_to_dataframe`` -> ``RawTable``，与普通表格完全同构。

数值不做类型转换：``1,200`` 这类文本留给 ``normalize.py`` 的整列数值归一化
统一处理（它知道哪些列像编号、哪些列该保留字符串）。
"""
from __future__ import annotations

import re
from html.parser import HTMLParser

from service.runtime.utils import extract_json_from_response

# Markdown 分隔行：| --- | :---: | ---: |
_MD_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$")
_MD_EPHASIS_RE = re.compile(r"(\*\*|__|`)")
_HTML_SPACE_RE = re.compile(r"[\u00a0\u3000]+")


def parse_table_response(text: str) -> list[dict]:
    """解析模型输出，按 JSON -> Markdown -> HTML 的顺序尝试。

    Args:
        text: 模型返回的原始文本（可能含围栏/解释文字）

    Returns:
        表格载荷列表；没有任何可用表时返回空列表。
    """
    raw = str(text or "").strip()
    if not raw:
        return []

    payloads = _payloads_from_json(extract_json_from_response(raw))
    if payloads:
        return payloads

    payloads = _payloads_from_markdown(raw)
    if payloads:
        return payloads

    return _payloads_from_html(raw)


def is_explicit_empty_table(text: str) -> bool:
    """模型是否**明确**表示「图里没有表」。

    用于区分「模型说没有表」和「模型输出解析不了」：前者不该触发修复重试，
    后者值得再问一次。识别 ``{"columns": [], "rows": []}``、``{"tables": []}``
    以及它们的数组形式。
    """
    data = extract_json_from_response(str(text or ""))
    return _is_empty_json(data)


def _is_empty_json(data) -> bool:
    if isinstance(data, list):
        return not data
    if not isinstance(data, dict):
        return False
    nested = data.get("tables")
    if isinstance(nested, list) and not nested:
        return True
    columns = data.get("columns")
    if isinstance(columns, list) and not columns:
        return True
    for key in ("data", "table", "result"):
        wrapped = data.get(key)
        if isinstance(wrapped, (dict, list)) and _is_empty_json(wrapped):
            return True
    return False


# ----------------------------------------------------------------------
# JSON
# ----------------------------------------------------------------------

def _payloads_from_json(data) -> list[dict]:
    """把各种 JSON 形态归一成表格载荷列表。"""
    if data is None:
        return []
    if isinstance(data, list):
        items = [item for item in data if isinstance(item, dict)]
        return _clean_payloads(items)
    if not isinstance(data, dict):
        return []

    nested = data.get("tables")
    if isinstance(nested, list):
        items = [item for item in nested if isinstance(item, dict)]
        cleaned = _clean_payloads(items)
        if cleaned:
            return cleaned

    for key in ("data", "table", "result", "output"):
        wrapped = data.get(key)
        if isinstance(wrapped, (dict, list)):
            cleaned = _payloads_from_json(wrapped)
            if cleaned:
                return cleaned

    if data.get("columns") and data.get("rows"):
        return _clean_payloads([data])
    return []


def _clean_payloads(items: list[dict]) -> list[dict]:
    payloads = []
    for item in items:
        payload = _normalize_payload(item)
        if payload:
            payloads.append(payload)
    return payloads


def _normalize_payload(item: dict) -> dict | None:
    """rows 支持 ``[{列:值}]`` 与 ``[[值,...]]`` 两种写法。"""
    columns = item.get("columns")
    rows = item.get("rows")
    if not isinstance(columns, list) or not columns or not isinstance(rows, list):
        return None

    columns = [str(col).strip() for col in columns]
    normalized_rows: list[dict] = []
    for row in rows:
        if isinstance(row, dict):
            # 保留模型原始行：列名去重在 _to_dataframe 里做（重复列会改名为 值/值_2），
            # 这里按键重建会丢掉重复列对应的值。
            normalized_rows.append(row)
        elif isinstance(row, (list, tuple)):
            normalized_rows.append(
                {col: (row[index] if index < len(row) else None) for index, col in enumerate(columns)}
            )
    if not normalized_rows:
        return None

    payload = {"columns": columns, "rows": normalized_rows}
    title = str(item.get("title") or item.get("name") or "").strip()
    if title:
        payload["title"] = title
    return payload


# ----------------------------------------------------------------------
# Markdown
# ----------------------------------------------------------------------

def _payloads_from_markdown(text: str) -> list[dict]:
    lines = text.splitlines()
    payloads: list[dict] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        has_header = index > 0 and "|" in lines[index - 1]
        if not (_MD_SEPARATOR_RE.match(line) and has_header):
            index += 1
            continue

        header = _split_markdown_row(lines[index - 1])
        rows: list[list[str]] = []
        cursor = index + 1
        while cursor < len(lines) and lines[cursor].strip() and "|" in lines[cursor]:
            rows.append(_split_markdown_row(lines[cursor]))
            cursor += 1

        payload = _cells_to_payload(header, rows)
        if payload:
            payloads.append(payload)
        index = cursor
    return payloads


def _split_markdown_row(line: str) -> list[str]:
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|") and not text.endswith("\\|"):
        text = text[:-1]

    cells: list[str] = []
    buf: list[str] = []
    escaped = False
    for char in text:
        if escaped:
            buf.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "|":
            cells.append(_clean_markdown_cell("".join(buf)))
            buf = []
        else:
            buf.append(char)
    cells.append(_clean_markdown_cell("".join(buf)))
    return cells


def _clean_markdown_cell(cell: str) -> str:
    text = _MD_EPHASIS_RE.sub("", str(cell or ""))
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.I)
    text = text.replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", text).strip()


def _unique_columns(columns: list[str]) -> list[str]:
    """列名去空白/补空名/去重（Markdown/HTML 表可能有两列同名）。"""
    unique: list[str] = []
    seen: dict[str, int] = {}
    for index, raw in enumerate(columns):
        name = str(raw or "").strip() or f"col_{index + 1}"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 1
        unique.append(name)
    return unique


def _cells_to_payload(header: list[str], rows: list[list[str]]) -> dict | None:
    if not rows:
        return None

    width = max([len(header)] + [len(row) for row in rows])
    columns = _unique_columns(list(header) + [f"列{i + 1}" for i in range(len(header), width)])

    normalized_rows = []
    for row in rows:
        padded = list(row) + [None] * (width - len(row))
        if not any(value not in (None, "") for value in padded):
            continue
        normalized_rows.append({col: padded[i] for i, col in enumerate(columns)})
    if not normalized_rows:
        return None
    return {"columns": columns, "rows": normalized_rows}


# ----------------------------------------------------------------------
# HTML
# ----------------------------------------------------------------------

class _HtmlTableCollector(HTMLParser):
    """收集 HTML 表格为二维单元格，处理 colspan / rowspan。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[dict]]] = []
        self._tables: list[dict] = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "table":
            self._tables.append({"rows": [], "row": None, "cell": None})
            return
        if not self._tables:
            return

        table = self._tables[-1]
        if tag == "tr":
            table["row"] = []
        elif tag in ("td", "th"):
            if table["row"] is None:
                table["row"] = []
            attrs = dict(attrs)
            cell = {
                "text": [],
                "header": tag == "th",
                "colspan": _span(attrs.get("colspan")),
                "rowspan": _span(attrs.get("rowspan")),
            }
            table["row"].append(cell)
            table["cell"] = cell
        elif tag == "br" and table["cell"] is not None:
            table["cell"]["text"].append(" ")

    def handle_data(self, data):
        if self._tables and self._tables[-1]["cell"] is not None:
            self._tables[-1]["cell"]["text"].append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if not self._tables:
            return
        table = self._tables[-1]
        if tag in ("td", "th"):
            table["cell"] = None
        elif tag == "tr":
            if table["row"] is not None:
                table["rows"].append(table["row"])
            table["row"] = None
        elif tag == "table":
            finished = self._tables.pop()
            if finished["rows"]:
                self.tables.append(finished["rows"])


def _span(value) -> int:
    try:
        return max(1, min(int(value), 50))
    except (TypeError, ValueError):
        return 1


def _payloads_from_html(text: str) -> list[dict]:
    if "<table" not in text.lower():
        return []

    collector = _HtmlTableCollector()
    try:
        collector.feed(text)
        collector.close()
    except Exception:  # 畸形 HTML 不该让整次抽表失败
        return []

    payloads = []
    for cells in collector.tables:
        payload = _html_cells_to_payload(cells)
        if payload:
            payloads.append(payload)
    return payloads


def _html_cells_to_payload(rows: list[list[dict]]) -> dict | None:
    expanded = _expand_html_grid(rows)
    if not expanded:
        return None
    grid, header_flags = expanded

    width = len(grid[0])
    header_count = 0
    for row_index, row in enumerate(grid):
        non_empty = [
            (header_flags[row_index][col], row[col])
            for col in range(width)
            if str(row[col] or "").strip()
        ]
        if non_empty and all(flag for flag, _ in non_empty):
            header_count += 1
        else:
            break
    header_count = max(1, header_count)

    if header_count > 1:
        # 多级表头（如 <th colspan=2>2023 年</th> + <th>Q1</th><th>Q2</th>）用 _ 连接
        columns = []
        for col in range(width):
            parts = [
                str(grid[row][col] or "").strip()
                for row in range(header_count)
                if str(grid[row][col] or "").strip()
            ]
            columns.append("_".join(parts))
    else:
        columns = [str(value or "").strip() for value in grid[0]]
    columns = _unique_columns(columns)

    normalized_rows = []
    for row in grid[header_count:]:
        padded = list(row) + [""] * (len(columns) - len(row))
        if not any(str(value or "").strip() for value in padded):
            continue
        normalized_rows.append({col: padded[i] for i, col in enumerate(columns)})
    if not normalized_rows:
        return None
    return {"columns": columns, "rows": normalized_rows}


def _expand_html_grid(
    rows: list[list[dict]],
) -> tuple[list[list[str]], list[list[bool]]] | None:
    """按 colspan / rowspan 把稀疏单元格展开成矩形文本网格。

    合并单元格**重复填充**文本（与多模态 prompt 要求的"向下/向右填充"一致），
    这样下游 Series 拆分看到的是完整的一行一个观测值。

    Returns:
        ``(grid, header_flags)``；header_flags 标记每个格子是否来自 <th>，
        供多级表头拼接使用。
    """
    if not rows:
        return None

    width = max([sum(cell["colspan"] for cell in row) for row in rows] + [0])
    if width == 0:
        return None

    height = len(rows)
    for row_index, row in enumerate(rows):
        for cell in row:
            height = max(height, row_index + cell["rowspan"])

    grid = [["" for _ in range(width)] for _ in range(height)]
    header_flags = [[False for _ in range(width)] for _ in range(height)]
    occupied = [[False for _ in range(width)] for _ in range(height)]

    for row_index, row in enumerate(rows):
        col_index = 0
        for cell in row:
            while col_index < width and occupied[row_index][col_index]:
                col_index += 1
            text = _HTML_SPACE_RE.sub(" ", "".join(cell["text"])).strip()
            for row_offset in range(cell["rowspan"]):
                target_row = row_index + row_offset
                if target_row >= height:
                    break
                for col_offset in range(cell["colspan"]):
                    target_col = col_index + col_offset
                    if target_col >= width:
                        break
                    if occupied[target_row][target_col]:
                        continue
                    grid[target_row][target_col] = text
                    header_flags[target_row][target_col] = bool(cell["header"])
                    occupied[target_row][target_col] = True
            col_index += cell["colspan"]

    keep = [index for index, row in enumerate(grid) if any(str(value or "").strip() for value in row)]
    if not keep:
        return None
    return (
        [grid[index] for index in keep],
        [header_flags[index] for index in keep],
    )
