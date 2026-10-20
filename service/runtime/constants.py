"""服务层公共常量。

集中放置多个模块共享的字面量，避免 magic string 与重复定义。
"""

from __future__ import annotations

import os
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# CSV 常见编码尝试顺序：优先 utf-8（含 BOM），随后中文常用编码，最后拉丁1兜底。
# 多处使用（file_adapter / file_read_cache / data_preview.compute_csv_preview）。
CSV_ENCODINGS: tuple[str, ...] = (
    "utf-8",
    "gbk",
    "gb2312",
    "gb18030",
    "latin1",
)


def get_charts_dir() -> Path:
    """统一图表输出/服务目录。

    读 CHARTS_DIR env，默认 <项目根>/runtime/charts。
    service_main 生成与 app.py /api/chart 服务共用此目录，避免不一致。
    """
    override = os.getenv("CHARTS_DIR", "").strip()
    if override:
        return Path(override)
    return _PROJECT_ROOT / "runtime" / "charts"


def get_vision_cache_dir() -> Path:
    """多模态抽表结果缓存目录。

    读 VISION_CACHE_DIR env，默认 <项目根>/runtime/cache/vision。
    按文件内容哈希存放，预览与图表任务共用，避免同一图片重复调用视觉模型。
    """
    override = os.getenv("VISION_CACHE_DIR", "").strip()
    if override:
        return Path(override)
    return _PROJECT_ROOT / "runtime" / "cache" / "vision"


def get_llm_text_cache_dir() -> Path:
    """文本表格化（HTML/Markdown/日志）结果缓存目录。

    读 LLM_TEXT_CACHE_DIR env，默认 <项目根>/runtime/cache/llm_text。
    与多模态缓存分开存放，便于分别清理。
    """
    override = os.getenv("LLM_TEXT_CACHE_DIR", "").strip()
    if override:
        return Path(override)
    return _PROJECT_ROOT / "runtime" / "cache" / "llm_text"
