"""DVS 视觉主题常量层（chart_polish 的单一来源）。

主题不是"选项类"，而是 options 的一个受控子集：调色板、字体、文字色阶。
把这些常量独立成模块的原因：

- chart_polish 只定"要不要改"，这里定"改成什么"；换品牌配色/字体只动本文件；
- 明暗两套 token 显式成对（标题/副标题/图例/轴标签/轴名/数据标签/tooltip 文字），
  深色模式不再东一处西一处散落十六进制串；
- 常量可单独断言（长度/唯一性/键齐全），主题回归不依赖渲染。

约定：调色板用 Tableau 10（明暗底上都可读）；dark token 只在 polish 显示
"深色需要反转"的场景使用，浅色 token 同理，双方都缺省的字段交给 ECharts 默认。
"""
from __future__ import annotations

# Tableau 10：色相区分度高，浅色/深色背景都能保持可读性
DVS_PALETTE: tuple[str, ...] = (
    "#4E79A7",
    "#F28E2B",
    "#E15759",
    "#76B7B2",
    "#59A14F",
    "#EDC948",
    "#B07AA1",
    "#FF9DA7",
    "#9C755F",
    "#BAB0AC",
)

# 中文无衬线字体栈（Windows/macOS/Linux 依次回退）
DVS_FONT_FAMILY = "Microsoft YaHei, PingFang SC, Hiragino Sans GB, Noto Sans CJK SC, sans-serif"

# 明暗文字色 token（dark 键按 polish_options(dark=True) 使用）
def _tone(
    *,
    title: str,
    subtitle: str,
    legend_text: str,
    axis_label: str,
    axis_name: str,
    data_label: str,
    tooltip_text: str,
    treemap_label: str,
    treemap_label_border: str,
    treemap_label_border_alt: str,
) -> dict[str, str]:
    """构造一套文字颜色 token（字段带默认语义，避免方括号取值写错）。"""
    return {
        "title": title,
        "subtitle": subtitle,
        "legend_text": legend_text,
        "axis_label": axis_label,
        "axis_name": axis_name,
        "data_label": data_label,
        "tooltip_text": tooltip_text,
        "treemap_label": treemap_label,
        # 矩形树图默认深色文字 + 浅色描边（黄/粉/浅蓝块上更清楚）
        "treemap_label_border": treemap_label_border,
        # 用户显式白字时的深色描边
        "treemap_label_border_alt": treemap_label_border_alt,
    }


TONE_LIGHT = _tone(
    title="#1f2937",
    subtitle="#6b7280",
    legend_text="#4b5563",
    axis_label="#4b5563",
    axis_name="#374151",
    data_label="#334155",
    # tooltip 文字色：浅色模式不设置（ECharts 默认深字 + 浅底弹框），
    # 该 token 仅在 polish 的 dark 分支使用，与 TONE_DARK.tooltip_text 相同
    tooltip_text="#f1f5f9",
    treemap_label="#1f2937",
    treemap_label_border="rgba(255, 255, 255, 0.9)",
    treemap_label_border_alt="rgba(15, 23, 42, 0.55)",
)

TONE_DARK = _tone(
    title="#f8fafc",
    subtitle="#cbd5e1",
    legend_text="#cbd5e1",
    axis_label="#cbd5e1",
    axis_name="#e2e8f0",
    data_label="#e2e8f0",
    tooltip_text="#f1f5f9",
    treemap_label="#1f2937",
    treemap_label_border="rgba(255, 255, 255, 0.9)",
    treemap_label_border_alt="rgba(15, 23, 42, 0.55)",
)


def tone_for(dark: bool) -> dict[str, str]:
    """按明暗取 token 套件（polish_options 统一入口）。"""
    return TONE_DARK if dark else TONE_LIGHT
