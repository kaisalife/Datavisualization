"""多模态表格化 Reader：图片 / PDF -> 结构化表格。

能力边界：
- 图片（png/jpg/jpeg/webp/bmp/gif/tif/tiff）：压缩后以 data URL 交给视觉模型。
- PDF：逐页渲染为图片后交给视觉模型（默认前 5 页），作为文字层解析失败时的兜底。

输出与其它 reader 一致：``list[RawTable]``，交给 series 拆分与图表生成。
LLM 可通过参数注入（测试用），默认读 ``.env`` 的 ``VISION_*`` 配置构造 ChatOpenAI。
"""
from __future__ import annotations

import base64
import io
import os
import re
from pathlib import Path

import pandas as pd

from service.data_ingestion import vision_cache
from service.data_ingestion.models import RawTable, safe_table_name
from service.data_ingestion.profiler import _is_time_label
from service.data_ingestion.readers.table_payload import (
    is_explicit_empty_table,
    parse_table_response,
)
from service.observability import get_logger
from service.runtime.utils import get_env_int, get_llm_extra_headers

logger = get_logger(__name__)

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".avif", ".heic", ".heif"}
_PDF_EXTS = {".pdf"}
_HEIF_EXTS = {".heic", ".heif"}

_MIME_FALLBACK = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".gif": "image/gif",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".avif": "image/avif",
}

_MAX_ROWS = 200
_DEFAULT_MAX_TABLES = 5
_heif_ready = False
_DEFAULT_MAX_SIDE = 2000
_DEFAULT_MAX_PDF_PAGES = 5
_PNG_EXTS = {".png", ".bmp", ".gif", ".tif", ".tiff"}
_MAX_PNG_BYTES = 4 * 1024 * 1024


def _load_env_llm(vision_cfg: dict | None = None):
    """构造视觉模型客户端。

    凭证优先级：VISION_* 环境变量 > 请求带来的模型配置 > .env 的 BASE_URL/API_KEY。
    模型名优先级：``VISION_MODEL_NAME`` > 请求里的 ``model_type``（前端设置里启用的
    模型）> ``MODEL_NAME`` > ``glm-4.5v``。请求级模型名必须生效：换厂商时前端只下发
    ``model_type``，写死缺省值会把 glm-4.5v 发到别家网关（400/模型不存在）。

    Args:
        vision_cfg: {"base_url": str, "api_key": str, "model": str}（来自请求，可为空）

    Returns:
        ChatOpenAI 实例

    Raises:
        RuntimeError: 凭证缺失
    """
    from dotenv import load_dotenv

    load_dotenv()

    cfg = vision_cfg or {}
    base_url = (
        os.getenv("VISION_BASE_URL", "").strip()
        or str(cfg.get("base_url") or "").strip()
        or os.getenv("BASE_URL", "").strip()
    )
    api_key = (
        os.getenv("VISION_API_KEY", "").strip()
        or str(cfg.get("api_key") or "").strip()
        or os.getenv("API_KEY", "").strip()
    )
    model = (
        os.getenv("VISION_MODEL_NAME", "").strip()
        or str(cfg.get("model") or "").strip()
        or os.getenv("MODEL_NAME", "").strip()
        or "glm-4.5v"
    )
    if not base_url or not api_key:
        raise RuntimeError(
            "未配置视觉模型凭证：请在 .env 设置 VISION_BASE_URL/VISION_API_KEY，"
            "或在请求里带上模型配置（model_url/model_api_key）"
        )

    from langchain_openai import ChatOpenAI

    logger.info("多模态表格化使用模型", model=model, base_url=base_url)
    return ChatOpenAI(
        base_url=base_url,
        api_key=api_key,
        model=model,
        temperature=0,
        max_tokens=get_env_int("VISION_MAX_TOKENS", 8192),
        timeout=get_env_int("VISION_TIMEOUT", 90),
        max_retries=2,
        default_headers=get_llm_extra_headers() or None,
    )


def load_vision_llm(vision_cfg: dict | None = None):
    """按 ``vision_cfg`` / ``VISION_*`` / ``.env`` 构造视觉模型客户端。

    供 OfficeImageReader 等复用；参数与 :func:`_load_env_llm` 一致。
    """
    return _load_env_llm(vision_cfg)


def _content_to_text(content) -> str:
    """兼容 str / list[block] 两种模型返回格式。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text", "")))
            else:
                parts.append(str(item))
        return "\n".join(p for p in parts if p)
    return str(content)


def _dedupe_columns(data: dict) -> dict:
    """列名去空白、补空名、去重（视觉模型常输出重复列名）。"""
    columns = []
    seen: dict[str, int] = {}
    for i, raw in enumerate(data.get("columns") or []):
        name = str(raw).strip() if raw is not None else ""
        name = name or f"col_{i + 1}"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 1
        columns.append(name)
    return {"columns": columns, "rows": data.get("rows") or []}


def _to_dataframe(data: dict) -> pd.DataFrame | None:
    """columns + rows -> DataFrame；行内缺列用 None 补齐。"""
    from service.data_ingestion.readers.llm_tabular_reader import to_dataframe

    data = _dedupe_columns(data)
    return to_dataframe(data)


def _register_heif() -> bool:
    """注册 HEIC/HEIF 解码器（pillow-heif 为可选依赖，缺失时返回 False）。

    返回:
        是否可用（重复调用只注册一次）
    """
    global _heif_ready
    if _heif_ready:
        return True
    try:
        from pillow_heif import register_heif_opener
    except ImportError:
        return False
    register_heif_opener()
    _heif_ready = True
    return True


def _image_to_data_url_from_pil(pil_image, ext: str) -> str:
    """PIL 图片 -> data URL；截图类优先 PNG，过大时降级 JPEG。"""
    from PIL import Image, ImageOps

    img = ImageOps.exif_transpose(pil_image)
    if img.mode not in ("RGB", "L"):
        # 透明背景铺白，避免转 RGB 后变黑
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[-1])
            img = background
        else:
            img = img.convert("RGB")
    elif img.mode == "L":
        img = img.convert("RGB")

    max_side = get_env_int("VISION_MAX_IMAGE_SIDE", _DEFAULT_MAX_SIDE)
    img.thumbnail((max_side, max_side))

    ext = ext.lower()
    if ext in _PNG_EXTS:
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        payload = buf.getvalue()
        mime = "image/png"
        if len(payload) > _MAX_PNG_BYTES:
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85, optimize=True)
            payload = buf.getvalue()
            mime = "image/jpeg"
    else:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=88, optimize=True)
        payload = buf.getvalue()
        mime = "image/jpeg"

    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _image_to_data_url(path: Path) -> str:
    """图片文件 -> data URL。"""
    from PIL import Image

    if path.suffix.lower() in _HEIF_EXTS and not _register_heif():
        raise RuntimeError(
            "读取 HEIC/HEIF 需要 pillow-heif：请执行 "
            "pip install -i https://pypi.tuna.tsinghua.edu.cn/simple pillow-heif"
        )
    with Image.open(path) as img:
        return _image_to_data_url_from_pil(img, path.suffix)


def image_bytes_to_data_url(payload: bytes, suffix: str) -> str:
    """内存中的图片字节 -> data URL（供 OOXML 内嵌图片复用）。

    Args:
        payload: 图片原始字节
        suffix: 文件扩展名（决定 mime 与编码策略，如 ".png"）

    Returns:
        ``data:image/...;base64,...``
    """
    from PIL import Image

    if suffix.lower() in _HEIF_EXTS and not _register_heif():
        raise RuntimeError(
            "读取 HEIC/HEIF 需要 pillow-heif：请执行 "
            "pip install -i https://pypi.tuna.tsinghua.edu.cn/simple pillow-heif"
        )
    with Image.open(io.BytesIO(payload)) as img:
        return _image_to_data_url_from_pil(img, suffix)


def _pdf_page_data_urls(path: Path, max_pages: int) -> list[str]:
    """PDF 前 N 页渲染为 data URL 列表。"""
    try:
        import pypdfium2 as pdfium
    except ImportError as e:
        raise RuntimeError("PDF 多模态解析需要 pypdfium2，请先安装") from e

    doc = pdfium.PdfDocument(str(path))
    urls: list[str] = []
    try:
        for index in range(min(len(doc), max_pages)):
            page = doc[index]
            try:
                bitmap = page.render(scale=2.0)
                urls.append(_image_to_data_url_from_pil(bitmap.to_pil(), ".png"))
            finally:
                page.close()
    finally:
        doc.close()
    return urls


def _parse_tables_payload(text: str) -> list[dict]:
    """解析视觉模型输出（JSON / Markdown / HTML），实现见 ``table_payload``。"""
    return parse_table_response(text)


def _vision_response_text(resp) -> str:
    """取模型文本；推理模型把 max_tokens 花光时给出可操作的报错。"""
    content = resp["content"] if isinstance(resp, dict) else getattr(resp, "content", resp)
    text = _content_to_text(content).strip()
    if text:
        return text

    if isinstance(resp, dict):
        reasoning = str(resp.get("reasoning_content") or "")
    else:
        reasoning = str((getattr(resp, "additional_kwargs", {}) or {}).get("reasoning_content") or "")
    if reasoning:
        raise RuntimeError(
            "模型只返回了 reasoning_content，max_tokens 可能被推理耗尽；"
            "请调大 VISION_MAX_TOKENS"
        )
    raise RuntimeError("视觉模型返回空内容")


_REPAIR_PROMPT = (
    "你上一条回复无法被解析成表格。请只输出 JSON，不要 Markdown 表格、不要解释文字。\n"
    '单表格式：{"columns": ["列名"], "rows": [{"列名": 值}]}\n'
    '多表格式：{"tables": [{"columns": [...], "rows": [...]}]}\n'
    '如果图中确实没有可用表格，输出 {"columns": [], "rows": []}。'
)


def _repair_enabled(repair_retry: bool | None) -> bool:
    """解析修复重试开关。

    不用 ``get_env_int``：它把 0 当非法值回退默认，``VISION_REPAIR_RETRY=0`` 反而失效。
    """
    if repair_retry is not None:
        return bool(repair_retry)
    raw = os.getenv("VISION_REPAIR_RETRY", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _retry_for_parseable_table(llm, messages: list, previous_text: str) -> str:
    """解析失败时追问一次：把不可解析的回复回填，要求只输出 JSON。"""
    from langchain_core.messages import AIMessage, HumanMessage

    retry_messages = list(messages) + [
        AIMessage(content=previous_text),
        HumanMessage(content=_REPAIR_PROMPT),
    ]
    resp = llm.invoke(retry_messages)
    return _vision_response_text(resp)


# PDF 跨页续表合并：只在证据明确时合并，避免把「按月拆开的独立快照表」拼在一起
_TOTAL_ROW_MARKERS = (
    "合计", "总计", "小计", "累计", "平均", "均值",
    "total", "subtotal", "average", "grandtotal",
)
_ROW_NA = "<NA>"


def _row_key(row) -> tuple[str, ...]:
    """行指纹：空值统一成哨兵，其余转字符串去首尾空白。"""
    return tuple(
        _ROW_NA if pd.isna(value) else str(value).strip()
        for value in row.tolist()
    )


def _is_total_row(row) -> bool:
    """判断一行是否是合计/小计/平均等汇总行。"""
    for value in row.tolist():
        if pd.isna(value):
            continue
        text = re.sub(r"[\s:：,，]+", "", str(value)).lower()
        if text and any(text.startswith(marker) for marker in _TOTAL_ROW_MARKERS):
            return True
    return False


def _can_merge_pdf_pages(previous: pd.DataFrame, current: pd.DataFrame) -> bool:
    """判断下一页的表是否是上一页的续表（保守规则）。

    合并条件：
    - 列结构与顺序完全一致，且至少两列；
    - 上一页最后一行、下一页第一行都不是合计/小计行；
    - 有时间列：上一页的时间序列尚未结束，下一页从更晚的时间继续
      （两页都只有一个固定期间时视为独立快照，如「1 月表」「2 月表」）；
    - 没有时间列：只有下一页重复了上一页最后一行（扫描/分页重叠）才合并。
    """
    if list(previous.columns) != list(current.columns) or len(previous.columns) < 2:
        return False
    if previous.empty or current.empty:
        return False
    if _is_total_row(previous.iloc[-1]) or _is_total_row(current.iloc[0]):
        return False

    time_cols = [col for col in previous.columns if _is_time_label(col)]
    if time_cols:
        col = time_cols[0]
        previous_times = previous[col].dropna()
        current_times = current[col].dropna()
        if previous_times.empty or current_times.empty:
            return False
        # 两页各自只有一个时间值：通常是按月/按日拆开的独立快照表，不合并
        if previous_times.nunique() <= 1 and current_times.nunique() <= 1:
            return False
        from service.data_ingestion.series.splitter import _natural_key

        return _natural_key(previous_times.iloc[-1]) < _natural_key(current_times.iloc[0])

    return _row_key(current.iloc[0]) == _row_key(previous.iloc[-1])


def _merge_pdf_continuation(previous: RawTable, current: RawTable) -> RawTable:
    """拼接两页续表；页边界重复行只保留一份。"""
    current_df = current.df
    if not current_df.empty and not previous.df.empty:
        if _row_key(current_df.iloc[0]) == _row_key(previous.df.iloc[-1]):
            current_df = current_df.iloc[1:]
    return RawTable(
        name=previous.name,
        df=pd.concat([previous.df, current_df], ignore_index=True),
        source_kind=previous.source_kind,
        source_path=previous.source_path,
        degraded=previous.degraded or current.degraded,
        degraded_reason=previous.degraded_reason or current.degraded_reason,
    )


def _merge_pdf_page_tables(
    page_groups: list[list[RawTable]], base_name: str, path: str
) -> list[RawTable]:
    """把相邻单表页按续表规则合并；多表页原样保留。"""
    merged_tables: list[RawTable] = []
    index = 0
    while index < len(page_groups):
        group = page_groups[index]
        if len(group) != 1:
            merged_tables.extend(group)
            index += 1
            continue

        current = group[0]
        last_index = index
        while last_index + 1 < len(page_groups) and len(page_groups[last_index + 1]) == 1:
            candidate = page_groups[last_index + 1][0]
            if not _can_merge_pdf_pages(current.df, candidate.df):
                break
            current = _merge_pdf_continuation(current, candidate)
            last_index += 1

        if last_index > index:
            first_page = index + 1
            last_page = last_index + 1
            current.name = base_name if first_page == 1 else f"{base_name}_p{first_page}"
            current.source_path = f"{path}#page{first_page}-{last_page}"
            logger.info(
                "PDF 跨页续表已合并",
                path=path,
                first_page=first_page,
                last_page=last_page,
                rows=len(current.df),
            )
        merged_tables.append(current)
        index = last_index + 1
    return merged_tables


def extract_tables_from_image(
    llm,
    image_url: str,
    hint: str = "",
    multi_table: bool = False,
    max_tables: int | None = None,
    repair_retry: bool | None = None,
) -> list[pd.DataFrame]:
    """调用视觉模型抽取单张图片中的表格。

    Args:
        llm: 视觉模型（须有 ``invoke(messages)``）
        image_url: data URL
        hint: 用户分析意图
        multi_table: True 时要求逐张输出所有表；False 只取一张主表
        max_tables: 最多保留几张（默认 ``VISION_MAX_TABLES`` 或 5）
        repair_retry: 模型输出解析不了时是否追问一次（默认 ``VISION_REPAIR_RETRY``=1）；
            模型**明确**回答「没有表」时不追问

    Returns:
        DataFrame 列表（无表时为空列表）
    """
    from prompts.multimodal_tabularize_prompt import build_multimodal_tabularize_messages

    messages = build_multimodal_tabularize_messages(
        image_url, hint=hint, multi_table=multi_table
    )
    text = _vision_response_text(llm.invoke(messages))

    items = _parse_tables_payload(text)
    # 模型输出成 Markdown/HTML/夹带解释时值得再问一次；明确空表说明模型认为没有数据
    if not items and _repair_enabled(repair_retry) and not is_explicit_empty_table(text):
        try:
            repaired = _retry_for_parseable_table(llm, messages, text)
        except Exception as e:  # 追问失败不影响原始报错路径
            logger.warning("多模态表格解析修复重试失败", error=str(e))
        else:
            repaired_items = _parse_tables_payload(repaired)
            if repaired_items:
                logger.info(
                    "多模态表格解析修复重试成功",
                    original_chars=len(text),
                    repaired_chars=len(repaired),
                )
                items = repaired_items

    limit = max_tables or get_env_int("VISION_MAX_TABLES", _DEFAULT_MAX_TABLES)
    if not multi_table:
        # 单表模式即使模型返回了 tables 数组，也只保留第一张
        limit = 1
    dataframes: list[pd.DataFrame] = []
    for item in items[:limit]:
        df = _to_dataframe(item)
        if df is not None and not df.empty:
            dataframes.append(df)
    return dataframes


def extract_table_from_image(llm, image_url: str, hint: str = "") -> pd.DataFrame | None:
    """单表模式：返回图片中的第一张表（兼容只取主表的调用方）。"""
    dataframes = extract_tables_from_image(llm, image_url, hint, multi_table=False)
    return dataframes[0] if dataframes else None


class MultimodalReader:
    """视觉模型驱动的表格化 Reader。"""

    @staticmethod
    def is_image(path: str | Path) -> bool:
        return Path(path).suffix.lower() in _IMAGE_EXTS

    @staticmethod
    def is_pdf(path: str | Path) -> bool:
        return Path(path).suffix.lower() in _PDF_EXTS

    @staticmethod
    def can_handle(path: str | Path) -> bool:
        return MultimodalReader.is_image(path) or MultimodalReader.is_pdf(path)

    @staticmethod
    def read(
        path: str,
        table_name: str | None = None,
        llm=None,
        hint: str = "",
        max_pages: int | None = None,
        vision_cfg: dict | None = None,
        multi_table: bool | None = None,
    ) -> list[RawTable]:
        """把图片 / PDF 转成结构化表格。

        Args:
            path: 图片或 PDF 路径
            table_name: 目标表名（默认取文件名）
            llm: 注入的视觉模型（须有 invoke(messages)）；None 时按 vision_cfg/.env 构造
            hint: 用户分析意图，帮助模型从多张表中选主表
            max_pages: PDF 最多解析页数（默认 VISION_MAX_PDF_PAGES 或 5）
            vision_cfg: 请求带来的模型配置 {"base_url","api_key"}
            multi_table: True 时抽出图中所有表（一图多条 RawTable）；
                None 时读 ``VISION_MULTI_TABLE``（默认 0，只取主表）

        Returns:
            list[RawTable]（图片 1 条；PDF 每页有表格则各 1 条，跨页续表会按保守规则
            合并为 1 条；多表模式一图可多条）

        Raises:
            FileNotFoundError: 文件不存在
            RuntimeError: 视觉模型未配置或 PDF 渲染依赖缺失
            ValueError: 所有页面都未提取到结构化表格
        """
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"文件不存在: {path}")

        use_cache = llm is None
        llm = llm or _load_env_llm(vision_cfg)
        if multi_table is None:
            multi_table = bool(get_env_int("VISION_MULTI_TABLE", 0))
        effective_max_pages = max_pages or get_env_int(
            "VISION_MAX_PDF_PAGES", _DEFAULT_MAX_PDF_PAGES
        )

        base_name = safe_table_name(table_name or p.name)
        cache_key_value = None
        if use_cache and vision_cache.cache_enabled():
            cache_key_value = vision_cache.cache_key(
                p,
                base_name=base_name,
                hint=hint,
                multi_table=multi_table,
                max_pages=effective_max_pages,
                max_tables=get_env_int("VISION_MAX_TABLES", _DEFAULT_MAX_TABLES),
                max_side=get_env_int("VISION_MAX_IMAGE_SIDE", _DEFAULT_MAX_SIDE),
                signature=vision_cache.model_signature(llm),
            )
            cached = vision_cache.load_tables(cache_key_value, p)
            if cached:
                logger.info(
                    "多模态缓存命中",
                    path=str(p),
                    tables=len(cached),
                    rows=sum(len(t.df) for t in cached),
                )
                return cached

        if MultimodalReader.is_pdf(p):
            pages = _pdf_page_data_urls(p, effective_max_pages)
        else:
            pages = [_image_to_data_url(p)]

        page_groups: list[list[RawTable]] = []
        errors: list[str] = []
        multi_page = len(pages) > 1
        is_pdf = MultimodalReader.is_pdf(p)

        for index, image_url in enumerate(pages, start=1):
            try:
                dataframes = extract_tables_from_image(
                    llm, image_url, hint, multi_table=multi_table
                )
            except Exception as e:  # 单页失败不拖垮整个文件
                errors.append(f"page {index}: {type(e).__name__}: {e}")
                logger.warning("多模态单页解析失败", path=str(p), page=index, error=str(e), error_type=type(e).__name__)
                page_groups.append([])
                continue

            if not dataframes:
                logger.info("多模态未在该页提取到表格", path=str(p), page=index)
                page_groups.append([])
                continue

            page_tables: list[RawTable] = []
            for table_index, df in enumerate(dataframes, start=1):
                suffix = ""
                if multi_page:
                    suffix += f"_p{index}"
                if len(dataframes) > 1:
                    suffix += f"_t{table_index}"

                source_path = f"{path}#page{index}" if is_pdf else path
                if len(dataframes) > 1:
                    source_path += f"/table{table_index}"

                page_tables.append(
                    RawTable(
                        name=f"{base_name}{suffix}",
                        df=df,
                        source_kind="document",
                        source_path=source_path,
                    )
                )
            page_groups.append(page_tables)

        if is_pdf and multi_page:
            tables = _merge_pdf_page_tables(page_groups, base_name, path)
        else:
            tables = [table for group in page_groups for table in group]

        # 合并后的表可能超过单表行数上限，统一在最后截断
        for table in tables:
            if len(table.df) > _MAX_ROWS:
                table.df = table.df.head(_MAX_ROWS)

        if not tables:
            detail = f"；失败页: {'; '.join(errors[:3])}" if errors else ""
            raise ValueError(f"未从图片中提取到结构化表格: {p.name}{detail}")

        if cache_key_value:
            vision_cache.save_tables(cache_key_value, tables, p)

        logger.info(
            "多模态表格提取完成",
            path=str(p),
            pages=len(pages),
            tables=len(tables),
            rows=sum(len(t.df) for t in tables),
        )
        return tables
