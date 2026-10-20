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
from pathlib import Path

import pandas as pd

from service.data_ingestion.models import RawTable, safe_table_name
from service.observability import get_logger
from service.runtime.utils import get_env_int, get_llm_extra_headers

logger = get_logger(__name__)

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
_PDF_EXTS = {".pdf"}

_MIME_FALLBACK = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".gif": "image/gif",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}

_MAX_ROWS = 200
_DEFAULT_MAX_SIDE = 2000
_DEFAULT_MAX_PDF_PAGES = 5
_PNG_EXTS = {".png", ".bmp", ".gif", ".tif", ".tiff"}
_MAX_PNG_BYTES = 4 * 1024 * 1024


def _load_env_llm(vision_cfg: dict | None = None):
    """构造视觉模型客户端。

    凭证优先级：VISION_* 环境变量 > 请求带来的模型配置 > .env 的 BASE_URL/API_KEY。
    模型名：VISION_MODEL_NAME 环境变量，缺省 glm-4.5v（智谱；其它厂商需显式指定）。

    Args:
        vision_cfg: {"base_url": str, "api_key": str}（来自请求的模型配置，可为空）

    Returns:
        ChatOpenAI 实例

    Raises:
        RuntimeError: 凭证缺失或模型名不合规
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
    model = os.getenv("VISION_MODEL_NAME", "").strip() or "glm-4.5v"
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

    with Image.open(path) as img:
        return _image_to_data_url_from_pil(img, path.suffix)


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


def _extract_one(llm, image_url: str, hint: str) -> pd.DataFrame | None:
    """调用视觉模型抽取单张图片中的表格。"""
    from prompts.multimodal_tabularize_prompt import build_multimodal_tabularize_messages
    from service.data_ingestion.readers.llm_tabular_reader import parse_tabular_json

    messages = build_multimodal_tabularize_messages(image_url, hint=hint)
    resp = llm.invoke(messages)
    content = resp["content"] if isinstance(resp, dict) else getattr(resp, "content", resp)
    text = _content_to_text(content).strip()

    # 推理模型（reasoning_content）可能把 max_tokens 全用在思考上，最终 content 为空
    if not text:
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

    data = parse_tabular_json(text)
    return _to_dataframe(data) if data else None


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
    ) -> list[RawTable]:
        """把图片 / PDF 转成结构化表格。

        Args:
            path: 图片或 PDF 路径
            table_name: 目标表名（默认取文件名）
            llm: 注入的视觉模型（须有 invoke(messages)）；None 时按 vision_cfg/.env 构造
            hint: 用户分析意图，帮助模型从多张表中选主表
            max_pages: PDF 最多解析页数（默认 VISION_MAX_PDF_PAGES 或 5）
            vision_cfg: 请求带来的模型配置 {"base_url","api_key"}

        Returns:
            list[RawTable]（图片 1 条；PDF 每页有表格则各 1 条）

        Raises:
            FileNotFoundError: 文件不存在
            RuntimeError: 视觉模型未配置或 PDF 渲染依赖缺失
            ValueError: 所有页面都未提取到结构化表格
        """
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"文件不存在: {path}")

        llm = llm or _load_env_llm(vision_cfg)

        if MultimodalReader.is_pdf(p):
            pages = _pdf_page_data_urls(p, max_pages or get_env_int("VISION_MAX_PDF_PAGES", _DEFAULT_MAX_PDF_PAGES))
        else:
            pages = [_image_to_data_url(p)]

        base_name = safe_table_name(table_name or p.name)
        tables: list[RawTable] = []
        errors: list[str] = []

        for index, image_url in enumerate(pages, start=1):
            try:
                df = _extract_one(llm, image_url, hint)
            except Exception as e:  # 单页失败不拖垮整个文件
                errors.append(f"page {index}: {type(e).__name__}: {e}")
                logger.warning("多模态单页解析失败", path=str(p), page=index, error=str(e), error_type=type(e).__name__)
                continue

            if df is None or df.empty:
                logger.info("多模态未在该页提取到表格", path=str(p), page=index)
                continue

            if len(df) > _MAX_ROWS:
                df = df.head(_MAX_ROWS)

            multi = len(pages) > 1
            name = f"{base_name}_p{index}" if multi else base_name
            source_path = f"{path}#page{index}" if MultimodalReader.is_pdf(p) else path
            tables.append(
                RawTable(name=name, df=df, source_kind="document", source_path=source_path)
            )

        if not tables:
            detail = f"；失败页: {'; '.join(errors[:3])}" if errors else ""
            raise ValueError(f"未从图片中提取到结构化表格: {p.name}{detail}")

        logger.info(
            "多模态表格提取完成",
            path=str(p),
            pages=len(pages),
            tables=len(tables),
            rows=sum(len(t.df) for t in tables),
        )
        return tables
