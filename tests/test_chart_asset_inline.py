"""echarts 资产内联（离线自包含 HTML）：单元 + 渲染链路（无需网络，缓存预置）。

- inline_echarts_assets：CDN script 标签 → 内联内容（缓存命中 / 缺失退回 CDN / 开关关闭）；
- 渲染链路：execute_chart_code 产物 HTML 应不再引用 assets.pyecharts.org。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from service.pipeline.chart_asset_inliner import (
    inline_echarts_assets,
    inline_rendered_html,
)

pytestmark = pytest.mark.whitebox


CDN = "https://assets.pyecharts.org/assets/v6/echarts.min.js"
FAKE_JS = 'var echarts=function(){};/*伪 echarts 便于断言*/\n'


def _html_with(script_url: str) -> str:
    return (
        "<!DOCTYPE html>\n<html><head><title>x</title></head>\n<body>\n"
        f'<script type="text/javascript" src="{script_url}"></script>\n'
        "</body></html>\n"
    )


@pytest.fixture
def seeded_cache(tmp_path: Path) -> Path:
    cache_dir = tmp_path / "assets"
    target = cache_dir / "assets" / "v6"
    target.mkdir(parents=True)
    (target / "echarts.min.js").write_text(FAKE_JS, encoding="utf-8")
    return cache_dir


class TestInlineAssets:
    def test_inline_with_cached_asset(self, seeded_cache: Path):
        new_html, inlined, kept = inline_echarts_assets(
            _html_with(CDN), allow_download=False, cache_dir=seeded_cache
        )

        assert inlined == [CDN] and kept == []
        assert 'src="' not in new_html
        assert "伪 echarts" in new_html
        assert new_html.count("<script type=\"text/javascript\">") == 1

    def test_inline_multiple_assets(self, seeded_cache: Path):
        theme_url = "https://assets.pyecharts.org/assets/v6/themes/walden.js"
        (seeded_cache / "assets" / "v6" / "themes").mkdir(parents=True)
        (seeded_cache / "assets" / "v6" / "themes" / "walden.js").write_text(
            "var theme={color:['#001122']};", encoding="utf-8"
        )

        new_html, inlined, kept = inline_echarts_assets(
            _html_with(CDN).replace("</html></body>", "")
            + f'<script type="text/javascript" src="{theme_url}"></script>\n</body></html>\n',
            allow_download=False, cache_dir=seeded_cache,
        )

        assert sorted(inlined) == sorted([CDN, theme_url]) and kept == []
        assert "walden" not in new_html or 'src="http' not in new_html

    def test_missing_cache_keeps_cdn_link(self, tmp_path: Path):
        new_html, inlined, kept = inline_echarts_assets(
            _html_with(CDN), allow_download=False, cache_dir=tmp_path
        )

        assert inlined == [] and kept == [CDN]
        assert new_html == _html_with(CDN)  # 原样保留 CDN 链接

    def test_unsafe_content_not_inlined(self, seeded_cache: Path):
        """含 </script 字面量的脚本退回 CDN（防标签提前终止）。"""
        (seeded_cache / "assets" / "v6" / "echarts.min.js").write_text(
            FAKE_JS + 'var s="</script>";', encoding="utf-8"
        )

        new_html, inlined, kept = inline_echarts_assets(
            _html_with(CDN), allow_download=False, cache_dir=seeded_cache
        )

        assert inlined == [] and kept == [CDN]

    def test_disabled_env_noop(self, monkeypatch, seeded_cache: Path):
        monkeypatch.setenv("CHART_ASSETS_INLINE", "0")

        new_html, inlined, kept = inline_echarts_assets(
            _html_with(CDN), allow_download=False, cache_dir=seeded_cache
        )

        assert inlined == [] and kept == []
        assert new_html == _html_with(CDN)

    def test_traversal_url_rejected(self, tmp_path: Path):
        """路径穿越 URL 强校验（ensure 层抛错）；HTML 层不炸渲染、退回 CDN。"""
        from service.pipeline.chart_asset_inliner import ensure_remote_asset

        with pytest.raises(ValueError):
            ensure_remote_asset(
                "https://assets.pyecharts.org/assets/v6/../../etc/passwd.js",
                allow_download=False,
                cache_dir=tmp_path,
            )

        bad_html = _html_with("https://assets.pyecharts.org/assets/v6/../../etc/passwd.js")
        new_html, inlined, kept = inline_echarts_assets(
            bad_html, allow_download=False, cache_dir=tmp_path
        )
        assert inlined == [] and kept and new_html == bad_html

    def test_inline_rendered_html_writes_back(self, seeded_cache: Path, monkeypatch):
        f = seeded_cache.parent / "out.html"
        f.write_text(_html_with(CDN), encoding="utf-8")

        n, kept = inline_rendered_html(f, allow_download=False, cache_dir=seeded_cache)

        assert (n, kept) == (1, 0)
        assert "伪 echarts" in f.read_text(encoding="utf-8")

    def test_default_env_inline_on(self, seeded_cache: Path, monkeypatch):
        monkeypatch.setenv("CHART_ASSETS_INLINE", "1")

        new_html, inlined, _ = inline_echarts_assets(
            _html_with(CDN), allow_download=False, cache_dir=seeded_cache
        )

        assert inlined == [CDN] and "伪 echarts" in new_html


class TestRenderPipelineInline:
    def test_execute_chart_code_output_is_offline(self, monkeypatch, tmp_path: Path, seeded_cache: Path):
        """真实渲染链路：沙箱产物不再引用 CDN（网络缓存由 monkeypatch 注入 env）。"""
        monkeypatch.setenv("CHART_ASSETS_DIR", str(seeded_cache))
        monkeypatch.setenv("CHART_ASSETS_INLINE", "1")
        assert "CHART_ASSETS_DIR" in os.environ  # 沙箱复制父进程环境

        code = """
from pyecharts import options as opts
from pyecharts.charts import Bar

chart = (
    Bar()
    .add_xaxis(['北京', '上海', '广州'])
    .add_yaxis('销售额', [1200, 1500, 900])
    .set_global_opts(title_opts=opts.TitleOpts(title='各城市销售额'))
)
chart.render()
"""
        from service.pipeline.chart_sandbox import execute_chart_code
        result = execute_chart_code(code, charts_folder=tmp_path, plan_id="offline")

        assert result.success, result.output
        html = Path(result.chart_path).read_text(encoding="utf-8")
        assert "assets.pyecharts.org" not in html, "产物仍引用 CDN"
        assert "伪 echarts" in html
        # 原有润色/校验无回归
        assert "#4E79A7" in html and 'containLabel' in html.replace(" ", "")
