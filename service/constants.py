"""服务层公共常量。

集中放置多个模块共享的字面量，避免 magic string 与重复定义。
"""

from __future__ import annotations

# CSV 常见编码尝试顺序：优先 utf-8（含 BOM），随后中文常用编码，最后拉丁1兜底。
# 多处使用（file_adapter / file_read_cache / data_preview.compute_csv_preview）。
CSV_ENCODINGS: tuple[str, ...] = (
    "utf-8",
    "gbk",
    "gb2312",
    "gb18030",
    "latin1",
)
