"""自定义 SQL 的只读校验。

数据库数据源允许用户填「自定义 SQL」，但这条 SQL 会被直接交给驱动执行。
只读校验的目的是挡住误操作（把 `DROP TABLE` / `UPDATE` 粘进查询框）和
多语句注入（`SELECT 1; DROP TABLE sales`），而不是做完整的 SQL 解析：

- 允许：`SELECT` / `VALUES` / `SHOW` / `EXPLAIN` / `DESCRIBE`，以及以 `WITH`
  开头、主语句仍是 `SELECT` / `VALUES` 的 CTE 查询；
- 拒绝：任何以写操作开头或包含多条语句的 SQL。

校验前会先去掉字符串字面量与注释，避免把 `WHERE note = 'a;b'` 里的分号
误判成多语句。
"""

from __future__ import annotations

# 写操作 / DDL 关键字：出现在语句开头（或 WITH 的主语句位置）即拒绝
_WRITE_KEYWORDS = {
    "alter",
    "attach",
    "call",
    "create",
    "delete",
    "detach",
    "drop",
    "grant",
    "insert",
    "load",
    "merge",
    "replace",
    "revoke",
    "truncate",
    "update",
    "vacuum",
}

# 可以直接执行的只读语句
_READ_PREFIXES = {"select", "values", "show", "explain", "describe", "desc"}

_MSG = "自定义 SQL 只允许只读查询（SELECT / WITH / SHOW / EXPLAIN）"


def _strip_literals_and_comments(sql: str) -> str:
    """把字符串字面量和注释替换成空格，只保留 SQL 结构。"""
    out: list[str] = []
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]

        # 字符串 / 引用标识符：'...' "..." `...`，支持 '' 与反斜杠转义
        if ch in {"'", '"', "`"}:
            quote = ch
            i += 1
            while i < n:
                if sql[i] == "\\" and quote in {"'", '"'}:
                    i += 2
                    continue
                if sql[i] == quote:
                    if i + 1 < n and sql[i + 1] == quote:
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            out.append(" ")
            continue

        # -- 行注释
        if ch == "-" and i + 1 < n and sql[i + 1] == "-":
            i += 2
            while i < n and sql[i] not in "\r\n":
                i += 1
            out.append(" ")
            continue

        # /* 块注释 */
        if ch == "/" and i + 1 < n and sql[i + 1] == "*":
            i += 2
            while i + 1 < n and not (sql[i] == "*" and sql[i + 1] == "/"):
                i += 1
            i = min(i + 2, n)
            out.append(" ")
            continue

        out.append(ch)
        i += 1
    return "".join(out)


def _top_level_words(sql: str) -> list[str]:
    """返回括号深度为 0 的单词（小写），用于判断主语句类型。"""
    words: list[str] = []
    depth = 0
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if ch == "(":
            depth += 1
            i += 1
            continue
        if ch == ")":
            depth = max(0, depth - 1)
            i += 1
            continue
        if ch.isalpha() or ch == "_":
            j = i
            while j < n and (sql[j].isalnum() or sql[j] in {"_", "$"}):
                j += 1
            if depth == 0:
                words.append(sql[i:j].lower())
            i = j
            continue
        i += 1
    return words


def ensure_read_only(sql: str) -> None:
    """校验自定义 SQL 为单条只读查询。

    Args:
        sql: 用户填写的 SQL

    Raises:
        ValueError: 包含多条语句，或主语句不是只读查询
    """
    text = str(sql or "").strip()
    if not text:
        raise ValueError("自定义 SQL 不能为空")

    clean = _strip_literals_and_comments(text).strip()
    # 末尾分号是合法写法；去掉后再检查是否还有语句分隔符
    body = clean.rstrip(";").strip()
    if ";" in body:
        raise ValueError(f"{_MSG}，不能包含多条语句")
    if not body:
        raise ValueError("自定义 SQL 不能为空（只包含注释或分号）")

    words = _top_level_words(body)
    if not words:
        raise ValueError("自定义 SQL 不能为空")

    first = words[0]
    if first in _READ_PREFIXES:
        return

    if first == "with":
        # CTE 的括号内容深度 > 0，不会进入 words；主语句在深度 0 找到
        for word in words[1:]:
            if word in {"select", "values"}:
                return
            if word in _WRITE_KEYWORDS:
                raise ValueError(f"{_MSG}，检测到写操作: {word}")
        raise ValueError(f"{_MSG}，WITH 后未找到 SELECT 主语句")

    raise ValueError(f"{_MSG}，检测到: {first}")
