"""echarts 资产内联：渲染后的 HTML 摆脱 CDN 依赖（产物双击可打开）。

pyecharts 默认把 `<script src="https://assets.pyecharts.org/assets/v6/...">`
写进产物（globals.CurrentConfig.ONLINE_HOST）。在线没问题，但：

- 离线 / 内网 / 用户导出到本地的 HTML 打开是空白图；
- pyecharts 自带的 ``RenderOpts(is_embed_js=True)`` 虽然内联，但
  ``load_javascript_contents`` 每次渲染都要 HTTPS 下载一次（实测 12.2s / 1.1MB）。

本模块的替代方案：本地缓存 + ``_patched_render`` 渲染后就地替换。

- 缓存目录 ``get_chart_assets_dir()``（CHART_ASSETS_DIR 可覆盖），
  按 URL 子路径镜像（``assets/v6/echarts.min.js``、``assets/v6/themes/<名>.js``）；
- 首次缺失时一次网络下载（仅信任 assets.pyecharts.org，带超时与非空校验），
  下载失败则**保留 CDN 链接**（在线仍可用）并记日志，绝不阻断出图；
- ``CHART_ASSETS_INLINE=0`` 整体关闭；
- 含 ``</script`` 字面量的脚本不内联（防字符串/正则错义，退回 CDN）。
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from pathlib import Path
from typing import Any

from service.observability import get_logger

try:
    from service.runtime.constants import get_chart_assets_dir
except ImportError:  # pragma: no cover - 脚本直跑 / 沙箱差异
    from ..runtime.constants import get_chart_assets_dir  # type: ignore

logger = get_logger(__name__)

_ASSET_HOST = "assets.pyecharts.org"
_ASSET_PREFIX = f"https://{_ASSET_HOST}/"
# pyecharts 模板产出的 script 标签格式（见 render/templates/macro 163-175 行）
_SCRIPT_RE = re.compile(
    r'<script\s+type="text/javascript"\s+src="(' + re.escape(_ASSET_PREFIX) + r'[^"]+)">\s*</script>'
)

# 下载参数：与 python 3.12 标准库一致，显式超时避免沙箱卡死
_DOWNLOAD_TIMEOUT = 30
_MAX_ASSET_BYTES = 20 * 1024 * 1024  # 单文件上限（echarts.min.js ~1.1MB）


def _inline_enabled() -> bool:
    """CHART_ASSETS_INLINE 开关（默认开启）。"""
    return (os.getenv("CHART_ASSETS_INLINE") or "1").strip().lower() not in {
        "0", "false", "off", "no",
    }


def _url_to_cache_path(url: str, cache_dir: Path) -> Path:
    """URL 子路径镜像到缓存目录，抹掉多余分隔符并防御路径穿越。"""
    sub = url[len(_ASSET_PREFIX):] if url.startswith(_ASSET_PREFIX) else url
    parts = [p for p in re.split(r"[\\/]+", sub) if p]
    if any(p in {"..", "."} for p in parts) or not parts:
        raise ValueError(f"非法资产路径: {url}")
    return cache_dir.joinpath(*parts)


def _download(url: str, dest: Path) -> Path:
    """下载远程资产并落缓存（临时文件 + 原子替换，多进程/中断安全）。"""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "datavisual/1.0(+chart-assets-inliner)"},
    )
    with urllib.request.urlopen(req, timeout=_DOWNLOAD_TIMEOUT) as resp:
        data = resp.read(_MAX_ASSET_BYTES + 1)
    if not data:
        raise ValueError(f"下载为空: {url}")
    if len(data) > _MAX_ASSET_BYTES:
        raise ValueError(f"资产超过单文件上限: {url}")
    if b"echarts" not in data[:8192]:
        raise ValueError(f"内容形式不像 echarts 资产: {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(dest)
    return dest


def ensure_remote_asset(url: str, *, cache_dir: Path | None = None, allow_download: bool = True) -> Path:
    """取回资产：命中缓存读缓存，缺失且允许时下载，否则抛错（调用方退回 CDN）。"""
    dest = _url_to_cache_path(url, cache_dir if cache_dir is not None else get_chart_assets_dir())
    if dest.is_file() and dest.stat().st_size > 0:
        return dest
    if not allow_download:
        raise FileNotFoundError(f"资产未缓存: {url}")
    return _download(url, dest)


def inline_echarts_assets(
    html: str,
    *,
    allow_download: bool = True,
    cache_dir: Path | None = None,
) -> tuple[str, list[str], list[str]]:
    """把 HTML 里的 pyecharts CDN script 标签替换为内联内容。

    Args:
        html: 渲染后的 HTML 文本
        allow_download: 缓存缺失时是否允许联网下载（默认允许；测试可关）
        cache_dir: 缓存目录覆盖（测试注入）

    Returns:
        (新 HTML（无命中时原样）, 成功内联的 URL 列表, 保留 CDN 的 URL 列表)
    """
    inlined: list[str] = []
    kept_cdn: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        url = match.group(1)
        try:
            src = ensure_remote_asset(url, cache_dir=cache_dir, allow_download=allow_download)
            content = src.read_text(encoding="utf-8", errors="replace")
            if "</script" in content.lower():
                # 内联脚本里嵌入 "</script" 会提前终止标签（字符串/正则错义风险），退回 CDN
                raise ValueError("脚本包含 </script 字面量，不安全内联")
            inlined.append(url)
            return '<script type="text/javascript">\n' + content + "\n</script>"
        except Exception as e:
            logger.warning("echarts 资产内联失败，保留 CDN 链接", url=url, error=str(e))
            kept_cdn.append(url)
            return match.group(0)

    if not _inline_enabled():
        return html, inlined, kept_cdn
    return _SCRIPT_RE.sub(_replace, html), inlined, kept_cdn


def inline_rendered_html(path: str | Path, **kwargs: Any) -> tuple[int, int]:
    """对渲染产物就地内联（chart_sandbox 的 _patched_render 调用）。

    Returns:
        (内联数, 保留 CDN 数)。出错抛异常由调用方兜底为只记日志。
    """
    chart_file = Path(path)
    html = chart_file.read_text(encoding="utf-8", errors="replace")
    new_html, inlined, kept = inline_echarts_assets(html, **kwargs)
    if inlined:
        chart_file.write_text(new_html, encoding="utf-8")
    # 返回统计给调用方打日志（不向外打印 LLM 无关的大内容）
    summary = json.dumps({"inlined": len(inlined), "kept_cdn": len(kept)})
    logger.debug("echarts 资产内联完成", summary=summary)
    return len(inlined), len(kept)
