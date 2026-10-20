"""OOXML（docx / pptx / xlsx）内嵌图片 -> 结构化表格。

Word / PPT 里的表格经常是**截图或粘贴的图表**，Unstructured 只能读到文字层，
拿不到表结构。这里直接按 OOXML 的 zip 结构取内嵌图片：

    word/media/*  ·  ppt/media/*  ·  xl/media/*

逐张交给视觉模型抽表，产物与普通图片链路完全一致（``list[RawTable]``），
由 router 在"文字层退化/解析失败"时兜底调用。

过滤规则（避免把图标、logo 当表格送模型）：
- 字节数 >= ``VISION_MIN_IMAGE_BYTES``（默认 4096）
- 最短边 >= ``VISION_MIN_IMAGE_SIDE``（默认 160）
- 最多 ``VISION_MAX_OFFICE_IMAGES`` 张（默认 8），按文档内自然顺序
"""
from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

from service.data_ingestion.models import RawTable, safe_table_name
from service.data_ingestion.readers.multimodal_reader import (
    extract_tables_from_image,
    image_bytes_to_data_url,
    load_vision_llm,
)
from service.observability import get_logger
from service.runtime.utils import get_env_int

logger = get_logger(__name__)

_OFFICE_EXTS = {".docx", ".docm", ".pptx", ".pptm", ".xlsx", ".xlsm"}
_MEDIA_DIRS = ("word/media/", "ppt/media/", "xl/media/")
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}

_DEFAULT_MIN_BYTES = 4096
_DEFAULT_MIN_SIDE = 160
_DEFAULT_MAX_IMAGES = 8
_MAX_ROWS = 200


class NoEmbeddedImages(LookupError):
    """文件里没有可用图片（没有媒体文件，或都被尺寸/体积过滤掉）。"""


def _natural_key(name: str) -> list:
    """``image2.png`` 排在 ``image10.png`` 前面。"""
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", name)]


def _image_size(payload: bytes) -> tuple[int, int] | None:
    """返回图片 (width, height)；无法解码（如 EMF/WMF）返回 None。"""
    try:
        from PIL import Image

        with Image.open(io.BytesIO(payload)) as img:
            return img.size
    except Exception:
        return None


class OfficeImageReader:
    """把 Office 文档内嵌图片转成表格。"""

    @staticmethod
    def can_handle(path: str | Path) -> bool:
        return Path(path).suffix.lower() in _OFFICE_EXTS

    @staticmethod
    def extract_images(
        path: str | Path,
        min_bytes: int | None = None,
        min_side: int | None = None,
        max_images: int | None = None,
    ) -> list[tuple[str, bytes]]:
        """提取可用的内嵌图片。

        Args:
            path: docx / pptx / xlsx 路径
            min_bytes: 体积下限（默认读 ``VISION_MIN_IMAGE_BYTES``）
            min_side: 最短边下限（默认读 ``VISION_MIN_IMAGE_SIDE``）
            max_images: 最多取几张（默认读 ``VISION_MAX_OFFICE_IMAGES``）

        Returns:
            ``[(media_name, payload)]``，按文档内自然顺序

        Raises:
            FileNotFoundError: 文件不存在
            NoEmbeddedImages: 不是 OOXML 包，或没有通过过滤的图片
        """
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"文件不存在: {path}")

        min_bytes = min_bytes if min_bytes is not None else get_env_int(
            "VISION_MIN_IMAGE_BYTES", _DEFAULT_MIN_BYTES
        )
        min_side = min_side if min_side is not None else get_env_int(
            "VISION_MIN_IMAGE_SIDE", _DEFAULT_MIN_SIDE
        )
        max_images = max_images if max_images is not None else get_env_int(
            "VISION_MAX_OFFICE_IMAGES", _DEFAULT_MAX_IMAGES
        )

        if not zipfile.is_zipfile(p):
            raise NoEmbeddedImages(f"{p.name} 不是 OOXML 压缩包，无法读取内嵌图片")

        picked: list[tuple[str, bytes]] = []
        with zipfile.ZipFile(p) as zf:
            names = [
                name
                for name in zf.namelist()
                if name.startswith(_MEDIA_DIRS) and Path(name).suffix.lower() in _IMAGE_EXTS
            ]
            names.sort(key=_natural_key)

            for name in names:
                if len(picked) >= max_images:
                    break
                try:
                    payload = zf.read(name)
                except Exception as e:  # 损坏条目不应拖垮整个文档
                    logger.warning("内嵌图片读取失败", path=str(p), media=name, error=str(e))
                    continue

                if len(payload) < min_bytes:
                    continue

                size = _image_size(payload)
                if size is None:
                    logger.info("跳过多模态不支持的图片格式", path=str(p), media=name)
                    continue
                if min(size) < min_side:
                    continue

                picked.append((name, payload))

        if not picked:
            raise NoEmbeddedImages(
                f"{p.name} 中没有可用内嵌图片（阈值 {min_bytes}B / {min_side}px）"
            )

        logger.info("提取文档内嵌图片", path=str(p), count=len(picked))
        return picked

    @staticmethod
    def read(
        path: str,
        table_name: str | None = None,
        llm=None,
        hint: str = "",
        vision_cfg: dict | None = None,
        multi_table: bool | None = None,
    ) -> list[RawTable]:
        """把文档内嵌图片逐张转成表格。

        Args:
            path: docx / pptx / xlsx 路径
            table_name: 目标表名（默认取文件名）
            llm: 注入的视觉模型（测试用）；None 时按 vision_cfg / .env 构造
            hint: 用户分析意图，帮助模型从多张表中选主表
            vision_cfg: 请求带来的模型配置 ``{"base_url","api_key"}``
            multi_table: True 时每张图片里的所有表都抽出（同图多表命名 ``_t1``/``_t2``）；
                None 时读 ``VISION_MULTI_TABLE``（默认 0，只取主表）

        Returns:
            list[RawTable]（每张图片抽到表就一条；多表模式下一张图可多条）

        Raises:
            NoEmbeddedImages: 没有可用图片
            ValueError: 有图片但全部抽表失败
        """
        images = OfficeImageReader.extract_images(path)
        llm = llm or load_vision_llm(vision_cfg)
        if multi_table is None:
            multi_table = bool(get_env_int("VISION_MULTI_TABLE", 0))

        base_name = safe_table_name(table_name or Path(path).name)
        multi_image = len(images) > 1
        tables: list[RawTable] = []
        errors: list[str] = []

        for index, (media_name, payload) in enumerate(images, start=1):
            try:
                data_url = image_bytes_to_data_url(payload, Path(media_name).suffix)
                dataframes = extract_tables_from_image(
                    llm, data_url, hint, multi_table=multi_table
                )
            except Exception as e:
                errors.append(f"{media_name}: {type(e).__name__}: {e}")
                logger.warning(
                    "内嵌图片抽表失败",
                    path=str(path),
                    media=media_name,
                    error=str(e),
                    error_type=type(e).__name__,
                )
                continue

            if not dataframes:
                logger.info("内嵌图片未提取到表格", path=str(path), media=media_name)
                continue

            for table_index, df in enumerate(dataframes, start=1):
                if len(df) > _MAX_ROWS:
                    df = df.head(_MAX_ROWS)

                suffix = f"_img{index}" if multi_image else ""
                if len(dataframes) > 1:
                    suffix += f"_t{table_index}"

                source_path = f"{path}#{media_name}"
                if len(dataframes) > 1:
                    source_path += f"/table{table_index}"

                tables.append(
                    RawTable(
                        name=f"{base_name}{suffix}",
                        df=df,
                        source_kind="document",
                        source_path=source_path,
                    )
                )

        if not tables:
            detail = f"；失败: {'; '.join(errors[:3])}" if errors else ""
            raise ValueError(f"文档内嵌图片均未提取到表格: {Path(path).name}{detail}")

        logger.info(
            "文档内嵌图片抽表完成",
            path=str(path),
            images=len(images),
            tables=len(tables),
        )
        return tables
