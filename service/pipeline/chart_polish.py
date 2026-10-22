"""图表渲染前的视觉质量后处理。

LLM 生成的 pyecharts 代码通常能出图，但常见问题很一致：柱状图标签默认落在柱子里、
大数字没有千分位、类目标签相互遮挡、饼图半径过大、柱宽失控、tooltip 触发方式不合适。
这些问题不适合全部交给 prompt（模型会漏），也不适合失败重试（代码本身没报错）。

本模块在 ``chart_sandbox`` 的 render monkey-patch 中、真正落盘前调用，
只补缺失项或修正明显不合理的默认值；用户显式设置的配色、标签位置、tooltip
触发方式等一律保留。``polish_options`` 是纯函数，便于单测。
"""
from __future__ import annotations

import copy
import re
from typing import Any, Iterator

try:
    from pyecharts.commons.utils import JsCode
    from pyecharts.options.series_options import BasicOpts
except ImportError:  # pragma: no cover - pyecharts 是运行期硬依赖
    JsCode = None  # type: ignore[assignment]
    BasicOpts = ()  # type: ignore[assignment]

try:
    from service.pipeline.chart_theme import DVS_FONT_FAMILY as FONT_FAMILY
    from service.pipeline.chart_theme import DVS_PALETTE as PALETTE
    from service.pipeline.chart_theme import tone_for
except ImportError:  # pragma: no cover - 沙箱双导入差异
    from .chart_theme import DVS_FONT_FAMILY as FONT_FAMILY  # type: ignore
    from .chart_theme import DVS_PALETTE as PALETTE  # type: ignore
    from .chart_theme import tone_for  # type: ignore

# 坐标轴 / 数据标签的大数字统一加千分位；数值型之外的值原样返回
_THOUSANDS_JS = (
    "function (value) {"
    " if (typeof value !== 'number') { return value; }"
    " return value.toLocaleString('zh-CN');"
    "}"
)
_LABEL_VALUE_JS = (
    "function (p) {"
    " var v = p && p.value;"
    " if (v === null || v === undefined) { return ''; }"
    " if (typeof v === 'number') {"
    " return v.toLocaleString('zh-CN', { maximumFractionDigits: 2 });"
    " }"
    " return v;"
    "}"
)
# 柱状图/直方图的 0 值标签没有信息量，且稀疏分箱时会把画布塞满
_LABEL_VALUE_JS_HIDE_ZERO = (
    "function (p) {"
    " var v = p && p.value;"
    " if (v === null || v === undefined || v === 0) { return ''; }"
    " if (typeof v === 'number') {"
    " return v.toLocaleString('zh-CN', { maximumFractionDigits: 2 });"
    " }"
    " return v;"
    "}"
)
_TOOLTIP_VALUE_JS = (
    "function (value) {"
    " if (Array.isArray(value)) {"
    " return value.map(function (item) {"
    " return typeof item === 'number'"
    " ? item.toLocaleString('zh-CN', { maximumFractionDigits: 2 })"
    " : item;"
    " }).join(' / ');"
    " }"
    " if (typeof value !== 'number') { return value; }"
    " return value.toLocaleString('zh-CN', { maximumFractionDigits: 2 });"
    "}"
)

_CARTESIAN_SERIES = {
    "bar",
    "line",
    "scatter",
    "effectscatter",
    "candlestick",
    "boxplot",
    "heatmap",
}
_ITEM_TRIGGER_SERIES = {
    "pie",
    "funnel",
    "gauge",
    "radar",
    "heatmap",
    "wordcloud",
    "graph",
    "treemap",
    "sankey",
}


def _opts_dict(node: Any) -> dict[str, Any] | None:
    """把 pyecharts 的 BasicOpts / dict 统一成可写 dict。"""
    if isinstance(node, dict):
        return node
    if BasicOpts and isinstance(node, BasicOpts):
        raw = getattr(node, "opts", None)
        if isinstance(raw, dict):
            return raw
    return None


def _iter_dicts(value: Any) -> Iterator[dict[str, Any]]:
    """遍历选项对象/选项列表，展开 BasicOpts.opts（可能是 dict 或 list）。"""
    if value is None:
        return
    items = value if isinstance(value, (list, tuple)) else [value]
    for item in items:
        if isinstance(item, dict):
            yield item
            continue
        if BasicOpts and isinstance(item, BasicOpts):
            raw = getattr(item, "opts", None)
            if isinstance(raw, dict):
                yield raw
            elif isinstance(raw, (list, tuple)):
                for sub_item in raw:
                    if isinstance(sub_item, dict):
                        yield sub_item


def _ensure_dict(container: dict[str, Any], key: str) -> dict[str, Any] | None:
    """取得 container[key] 的可写 dict；缺失时创建普通 dict。"""
    value = container.get(key)
    node = _opts_dict(value)
    if node is not None:
        return node
    if value is None:
        node = {}
        container[key] = node
        return node
    # 列表等复杂结构不在这里处理
    return None


def _set_missing(target: dict[str, Any], key: str, value: Any) -> None:
    """仅在字段缺失（None）时写入，保留显式配置。"""
    if target.get(key) is None:
        target[key] = value


def _display_width(text: Any) -> int:
    """估算显示宽度：中文/全角字符按 2 个西文单位计算。"""
    return sum(2 if ord(ch) > 127 else 1 for ch in str(text or ""))


def _parse_width(width: Any, default: int = 900) -> int:
    """从 ``900px`` / 900 这类值里取出像素宽度。"""
    if isinstance(width, (int, float)):
        return int(width)
    match = re.search(r"(\d+(?:\.\d+)?)", str(width or ""))
    return int(float(match.group(1))) if match else default


def _series(options: dict[str, Any]) -> list[dict[str, Any]]:
    return list(_iter_dicts(options.get("series")))


def _series_types(options: dict[str, Any]) -> set[str]:
    return {
        str(node.get("type") or "").lower()
        for node in _series(options)
        if node.get("type")
    }


def _axis_nodes(options: dict[str, Any]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for key in ("xAxis", "yAxis"):
        nodes.extend(_iter_dicts(options.get(key)))
    return nodes


def _axis_is_category(axis: dict[str, Any] | None) -> bool:
    if axis is None:
        return False
    axis_type = str(axis.get("type") or "").lower()
    if axis_type == "category":
        return True
    if axis_type:
        return False
    data = axis.get("data")
    return isinstance(data, (list, tuple)) and len(data) > 0


def _axis_is_value(axis: dict[str, Any] | None) -> bool:
    if axis is None:
        return False
    axis_type = str(axis.get("type") or "").lower()
    if axis_type in {"value", "log"}:
        return True
    if axis_type:
        return False
    data = axis.get("data")
    return not isinstance(data, (list, tuple)) or len(data) == 0


def _axis_label_rotate(axis: dict[str, Any] | None) -> int:
    """读取类目标签旋转角度；缺省/非法值按 0 处理。"""
    if axis is None:
        return 0
    label = _opts_dict(axis.get("axisLabel"))
    if label is None:
        return 0
    try:
        return abs(int(label.get("rotate") or 0))
    except (TypeError, ValueError):
        return 0


def _is_cartesian(options: dict[str, Any]) -> bool:
    if not (_series_types(options) & _CARTESIAN_SERIES):
        return False
    return bool(_axis_nodes(options))


def _is_horizontal_bar(options: dict[str, Any]) -> bool:
    x_axis = next(iter(_iter_dicts(options.get("xAxis"))), None)
    y_axis = next(iter(_iter_dicts(options.get("yAxis"))), None)
    return _axis_is_value(x_axis) and _axis_is_category(y_axis)


def _position_pct(value: Any) -> float | None:
    """解析 top/bottom 的百分比或像素值。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().lower()
    if text in {"auto", "top"}:
        return 0.0
    if text in {"bottom"}:
        return 100.0
    match = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*%", text)
    if match:
        return float(match.group(1))
    match = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*(?:px)?", text)
    if match:
        return float(match.group(1)) / 9.0  # 约等于 900px 画布的百分比
    return None


def _position_px(value: Any, total: int, default: float = 0.0) -> float:
    """把 left/right 的百分比或像素值换算成像素。"""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().lower()
    match = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*%", text)
    if match:
        return float(match.group(1)) * total / 100.0
    match = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*(?:px)?", text)
    if match:
        return float(match.group(1))
    return default


def _legend_at_top(legend: dict[str, Any]) -> bool:
    if legend.get("bottom") is not None:
        return False
    top = _position_pct(legend.get("top"))
    return top is None or top <= 12


def _legend_at_bottom(legend: dict[str, Any]) -> bool:
    if legend.get("top") is not None:
        return False
    bottom = _position_pct(legend.get("bottom"))
    # bottom 是"距底部"的距离，2% 表示贴底
    return bottom is not None and bottom <= 12


def _legend_names(legend: dict[str, Any], series: list[dict[str, Any]]) -> list[str]:
    data = legend.get("data")
    names = [str(item) for item in data if item] if isinstance(data, list) else []
    if not names:
        names = [str(node.get("name")) for node in series if node.get("name")]
    return names


def _should_move_legend_bottom(
    options: dict[str, Any],
    *,
    width: int,
    series: list[dict[str, Any]],
) -> bool:
    """标题与水平顶部图例宽度相加会撞车时，把图例移到下方。"""
    legends = list(_iter_dicts(options.get("legend")))
    if len(legends) != 1:
        return False
    legend = legends[0]
    if legend.get("show") is False:
        return False
    if str(legend.get("orient") or "horizontal").lower() != "horizontal":
        return False
    if not _legend_at_top(legend):
        return False

    titles = [node for node in _iter_dicts(options.get("title")) if str(node.get("text") or "").strip()]
    if not titles:
        return False
    # Grid 多图布局各自有标题/图例，移动会破坏版式
    grids = list(_iter_dicts(options.get("grid")))
    if len(grids) > 1:
        return False

    title_left = str(titles[0].get("left") or "").lower()
    legend_left = str(legend.get("left") or "").lower()
    if title_left in {"left", "0", "0%"} and (
        legend.get("right") is not None or legend_left in {"right", "90%"}
    ):
        return False

    # 默认图例在顶部居中，与居中标题必然重叠；直接移到底部
    legend_centered = legend.get("right") is None and legend_left in {"", "center", "50%"}
    if legend_centered:
        return True

    title_width = max(_display_width(node.get("text")) for node in titles) * 9
    legend_width = sum(
        25 + 6 + _display_width(name) * 6 + 10
        for name in _legend_names(legend, series)
    )

    # 图例在右上角：按标题实际占位判断右侧是否还有空间
    if legend.get("right") is not None or legend_left in {"right", "90%"}:
        right_px = _position_px(legend.get("right"), width, default=10.0)
        legend_left_px = width - right_px - legend_width
        if title_left in {"left", "0", "0%"}:
            title_right_px = 10 + title_width
        elif title_left in {"right", "90%"}:
            title_right_px = width - 10
        else:
            title_right_px = width / 2 + title_width / 2
        return title_right_px + 16 > legend_left_px

    # 图例在左上角/自定义左侧位置
    legend_left_px = _position_px(legend.get("left"), width, default=10.0)
    if title_left in {"left", "0", "0%"}:
        title_left_px = 10
    elif title_left in {"right", "90%"}:
        title_left_px = width - 10 - title_width
    else:
        title_left_px = width / 2 - title_width / 2
    return title_left_px < legend_left_px + legend_width + 16


def _polish_title(options: dict[str, Any], *, dark: bool, width: int, multi_grid: bool) -> None:
    tone = tone_for(dark)
    for title in _iter_dicts(options.get("title")):
        if title.get("left") is None and title.get("right") is None:
            title["left"] = "center"
        if not multi_grid and title.get("top") is None and title.get("bottom") is None:
            title["top"] = "2%"

        text = str(title.get("text") or "")
        text_style = _ensure_dict(title, "textStyle")
        if text_style is not None:
            _set_missing(text_style, "fontFamily", FONT_FAMILY)
            font_size = 16 if _display_width(text) * 9 > width * 0.9 else 18
            _set_missing(text_style, "fontSize", font_size)
            _set_missing(text_style, "fontWeight", "bold")
            _set_missing(text_style, "color", tone["title"])

        if title.get("subtext"):
            sub_style = _ensure_dict(title, "subtextStyle")
            if sub_style is not None:
                _set_missing(sub_style, "fontFamily", FONT_FAMILY)
                _set_missing(sub_style, "fontSize", 12)
                _set_missing(sub_style, "color", tone["subtitle"])


def _polish_legend(options: dict[str, Any], *, dark: bool) -> None:
    tone = tone_for(dark)
    for legend in _iter_dicts(options.get("legend")):
        text_style = _ensure_dict(legend, "textStyle")
        if text_style is None:
            continue
        _set_missing(text_style, "fontFamily", FONT_FAMILY)
        _set_missing(text_style, "fontSize", 12)
        _set_missing(text_style, "color", tone["legend_text"])


def _grid_signature(grid: dict[str, Any]) -> tuple:
    """比较 Grid 子图是否完全重叠（pyecharts 会把同一 GridOpts 复制成多份）。"""
    return tuple(
        str(grid.get(key))
        for key in ("top", "bottom", "left", "right", "width", "height", "containLabel")
    )


def _axis_family(axis: dict[str, Any], key: str) -> str:
    axis_type = str(axis.get("type") or "").lower()
    if not axis_type:
        return "category" if key == "xAxis" else "value"
    return axis_type


def _axis_names_compatible(axes: list[dict[str, Any]]) -> bool:
    names = {
        str(axis.get("name") or "").strip()
        for axis in axes
        if str(axis.get("name") or "").strip()
    }
    return len(names) <= 1


def _polish_overlay_grid(options: dict[str, Any]) -> None:
    """把“同一位置叠加的多个子图”合并回一套坐标轴。

    pyecharts 的 ``Grid.add`` 会为每个子图各建一套 xAxis/yAxis。箱线图叠加散点时，
    散点图常被添加 24 个重复类目，最终 x 轴出现一长串重复标签、y 轴刻度也会重影。
    只有在 Grid 位置完全相同、轴类型和轴名称兼容时才合并，避免破坏真正的多图布局
    或双轴图。
    """
    grids = list(_iter_dicts(options.get("grid")))
    x_axes = list(_iter_dicts(options.get("xAxis")))
    y_axes = list(_iter_dicts(options.get("yAxis")))
    series_nodes = _series(options)
    if len(grids) < 2 or len(x_axes) < 2 or len(y_axes) < 2 or len(series_nodes) < 2:
        return
    if len({_grid_signature(grid) for grid in grids}) != 1:
        return
    if len({_axis_family(axis, "xAxis") for axis in x_axes}) != 1:
        return
    if len({_axis_family(axis, "yAxis") for axis in y_axes}) != 1:
        return
    if not _axis_names_compatible(x_axes) or not _axis_names_compatible(y_axes):
        return

    for node in series_nodes:
        node["xAxisIndex"] = 0
        node["yAxisIndex"] = 0
        node["gridIndex"] = 0
    for axis in x_axes[1:]:
        axis["show"] = False
    for axis in y_axes[1:]:
        axis["show"] = False

    # 合并重复图例，只保留一份，避免底部出现两组重叠图例
    legends = list(_iter_dicts(options.get("legend")))
    if len(legends) > 1:
        merged: list[str] = []
        for legend in legends:
            for name in legend.get("data") or []:
                text = str(name)
                if text and text not in merged:
                    merged.append(text)
        if merged:
            legends[0]["data"] = merged
        legends[0]["show"] = True
        for legend in legends[1:]:
            legend["show"] = False


def _polish_grid(options: dict[str, Any]) -> None:
    if not _is_cartesian(options):
        return

    legends = list(_iter_dicts(options.get("legend")))
    legend_top = any(_legend_at_top(node) and node.get("show") is not False for node in legends)
    legend_bottom = any(_legend_at_bottom(node) and node.get("show") is not False for node in legends)
    has_title = any(str(node.get("text") or "").strip() for node in _iter_dicts(options.get("title")))
    has_data_zoom = bool(options.get("dataZoom"))

    if has_title and legend_top:
        default_top = "18%"
    elif has_title:
        default_top = "13%"
    else:
        default_top = "10%"

    # x 轴名称居中后需要额外的底部空间，否则会压住旋转后的类目标签或跑出画布
    x_axes = list(_iter_dicts(options.get("xAxis")))
    has_x_name = any(str(axis.get("name") or "").strip() for axis in x_axes)
    x_rotated = any(_axis_label_rotate(axis) > 0 for axis in x_axes)
    if has_x_name and x_rotated:
        default_bottom = "20%"
    elif has_x_name:
        default_bottom = "16%"
    elif has_data_zoom:
        default_bottom = "18%"
    elif legend_bottom:
        default_bottom = "14%"
    else:
        default_bottom = "10%"

    grids = list(_iter_dicts(options.get("grid")))
    if not grids:
        grid = {
            "containLabel": True,
            "top": default_top,
            "bottom": default_bottom,
            "left": "8%",
            "right": "4%",
        }
        options["grid"] = [grid]
        return

    for grid in grids:
        # containLabel 让 ECharts 把轴标签算进边距，显著减少左侧/底部裁切
        grid["containLabel"] = True
        if len(grids) == 1:
            _set_missing(grid, "top", default_top)
            _set_missing(grid, "bottom", default_bottom)
            _set_missing(grid, "left", "8%")
            _set_missing(grid, "right", "4%")
    # 多图 Grid 的间距由调用方控制，这里只补 containLabel，避免破坏布局


def _center_x_axis_name(axis: dict[str, Any]) -> None:
    """把默认靠右的 x 轴名称移到中间，避免长名称在画布右侧被裁掉。

    pyecharts 默认 ``nameLocation="end"``，名称贴着轴末端绘制，右侧只剩 4%–5%
    边距时经常只露出半个字。名称居中后按标签旋转角度补足 ``nameGap``；
    用户显式设置 ``start`` / ``middle`` 等位置时不改动。
    """
    if not str(axis.get("name") or "").strip():
        return
    location = str(axis.get("nameLocation") or "end").lower()
    if location not in {"", "end"}:
        return

    rotate = _axis_label_rotate(axis)
    gap = 30 if rotate <= 0 else int(48 + rotate * 0.55)
    axis["nameLocation"] = "middle"
    current_gap = axis.get("nameGap")
    if not isinstance(current_gap, (int, float)) or current_gap < gap:
        axis["nameGap"] = gap


def _normalize_mixed_area(options: dict[str, Any]) -> None:
    """多折线里只有部分系列带面积填充时，统一去掉填充。

    单条折线用面积强调量级没问题；多条折线里一条填充、一条不填充会让图例和
    视觉重量失衡（真实模型生成过这种代码）。全部系列都填充或都不填充则保留。
    """
    line_nodes = [
        node for node in _series(options)
        if str(node.get("type") or "").lower() == "line"
    ]
    if len(line_nodes) < 2:
        return

    def _visible(node: dict[str, Any]) -> bool:
        area = _opts_dict(node.get("areaStyle"))
        if not area:
            return False
        opacity = area.get("opacity")
        try:
            return opacity is None or float(opacity) > 0
        except (TypeError, ValueError):
            return True

    visible = [node for node in line_nodes if _visible(node)]
    if not visible or len(visible) == len(line_nodes):
        return
    for node in visible:
        area = _opts_dict(node.get("areaStyle"))
        if area is not None:
            area["opacity"] = 0


def _polish_axes(options: dict[str, Any], *, dark: bool, width: int) -> None:
    if not _is_cartesian(options):
        return
    tone = tone_for(dark)

    # 折线（无面积）且没有柱状系列时，让数值轴贴合数据范围。
    # 传感器温度 70–80℃、股票价格等从 0 开始会把真实波动压成一条平线；
    # 柱状图必须保留 0 基线，面积图的填充也从基线开始，因此这两类不自动改。
    series_nodes = _series(options)
    series_types = {str(node.get("type") or "").lower() for node in series_nodes}
    line_only = bool(series_types) and series_types <= {"line", "scatter", "effectscatter"}
    has_line = "line" in series_types

    def _area_is_visible(node: dict[str, Any]) -> bool:
        area = _opts_dict(node.get("areaStyle"))
        if not area:
            return False
        opacity = area.get("opacity")
        try:
            return opacity is None or float(opacity) > 0
        except (TypeError, ValueError):
            return True

    has_area = any(_area_is_visible(node) for node in series_nodes)
    if line_only and has_line and not has_area:
        for y_axis in _iter_dicts(options.get("yAxis")):
            if _axis_is_value(y_axis):
                # pyecharts 默认 scale=False，会把 70–80℃ 的波动压平；
                # 折线没有面积填充，贴合数据范围不会误导面积大小。
                y_axis["scale"] = True

    for axis_key in ("xAxis", "yAxis"):
        for axis in _iter_dicts(options.get(axis_key)):
            axis_label = _ensure_dict(axis, "axisLabel")
            if axis_label is not None:
                _set_missing(axis_label, "fontFamily", FONT_FAMILY)
                _set_missing(axis_label, "fontSize", 12)
                _set_missing(axis_label, "color", tone["axis_label"])

            name_style = _ensure_dict(axis, "nameTextStyle")
            if name_style is not None:
                _set_missing(name_style, "fontFamily", FONT_FAMILY)
                _set_missing(name_style, "fontSize", 12)
                _set_missing(name_style, "color", tone["axis_name"])

            if _axis_is_category(axis):
                if axis_key == "xAxis":
                    _rotate_category_labels(axis, axis_label, width=width)
                else:
                    _truncate_y_category_labels(axis, axis_label)
            elif _axis_is_value(axis):
                if axis_label is not None and axis_label.get("formatter") is None and JsCode is not None:
                    axis_label["formatter"] = JsCode(_THOUSANDS_JS)
                split_line = _ensure_dict(axis, "splitLine")
                if split_line is not None and split_line.get("show") is not False:
                    line_style = _ensure_dict(split_line, "lineStyle")
                    if line_style is not None:
                        _set_missing(line_style, "type", "dashed")
                        _set_missing(line_style, "opacity", 0.45)

            # 旋转角度确定后再居中轴名，才能按实际角度留出 nameGap
            if axis_key == "xAxis":
                _center_x_axis_name(axis)


def _rotate_category_labels(
    axis: dict[str, Any],
    axis_label: dict[str, Any] | None,
    *,
    width: int,
) -> None:
    if axis_label is None or axis_label.get("rotate") is not None:
        return
    data = axis.get("data")
    if not isinstance(data, (list, tuple)) or len(data) < 2:
        return

    count = len(data)
    max_width = max(_display_width(item) for item in data)
    # 粗略估算：每 1 个显示单位约 6px，画布 75% 用于类目标签
    ratio = count * max_width * 6.0 / max(width * 0.75, 1.0)
    rotate = 0
    if ratio >= 1.15:
        rotate = 30
    if ratio >= 1.7 or count > 24:
        rotate = 45
    if ratio >= 2.8 and max_width >= 16:
        rotate = 60
    if not rotate:
        return

    axis_label["rotate"] = rotate
    if count <= 20:
        _set_missing(axis_label, "interval", 0)


def _truncate_y_category_labels(
    axis: dict[str, Any],
    axis_label: dict[str, Any] | None,
) -> None:
    """横向柱状图的类目名放不下时截断，完整值仍可在 tooltip 看到。"""
    if axis_label is None or axis_label.get("width") is not None:
        return
    data = axis.get("data")
    if not isinstance(data, (list, tuple)) or not data:
        return
    max_width = max(_display_width(item) for item in data)
    if max_width <= 12:
        return
    axis_label["width"] = 140
    _set_missing(axis_label, "overflow", "truncate")


def _tooltip_has_custom_trigger(tooltip: dict[str, Any]) -> bool:
    """判断用户是否明确定制了 trigger/内容；定制后不再改默认触发方式。"""
    if tooltip.get("formatter"):
        return True
    if tooltip.get("triggerOn") not in (None, "mousemove|click"):
        return True
    if tooltip.get("position") is not None:
        return True
    axis_pointer = tooltip.get("axisPointer")
    if isinstance(axis_pointer, dict) and axis_pointer.get("type") not in (None, "line"):
        return True
    return False


def _tooltip_is_custom(tooltip: dict[str, Any]) -> bool:
    """判断 tooltip 是否带用户自定义内容（用于决定能否补默认 confine 等）。"""
    if _tooltip_has_custom_trigger(tooltip):
        return True
    if tooltip.get("confine") is True:
        return True
    if tooltip.get("valueFormatter") is not None:
        return True
    for key in ("backgroundColor", "borderColor", "extraCssText", "appendToBody"):
        if tooltip.get(key) not in (None, False, ""):
            return True
    return False


def _polish_tooltip(options: dict[str, Any], *, dark: bool) -> None:
    tooltips = list(_iter_dicts(options.get("tooltip")))
    if not tooltips:
        options["tooltip"] = {}
        tooltips = [options["tooltip"]]

    series_types = _series_types(options)
    default_trigger = "item" if series_types & _ITEM_TRIGGER_SERIES else "axis"
    axis_pointer_type = "shadow" if "bar" in series_types or "heatmap" in series_types else "line"

    for tooltip in tooltips:
        trigger_custom = _tooltip_has_custom_trigger(tooltip)
        custom = _tooltip_is_custom(tooltip)
        trigger = str(tooltip.get("trigger") or "").lower()
        if not trigger_custom and default_trigger == "axis" and trigger in {"", "item"}:
            # 柱/折线默认 item 只能看到单点，改为 axis 联动整行/整列
            tooltip["trigger"] = "axis"
            trigger = "axis"
        _set_missing(tooltip, "trigger", default_trigger)
        if tooltip.get("show") is False:
            continue
        if not custom:
            tooltip["confine"] = True
        if tooltip.get("valueFormatter") is None and JsCode is not None:
            tooltip["valueFormatter"] = JsCode(_TOOLTIP_VALUE_JS)

        text_style = _ensure_dict(tooltip, "textStyle")
        if text_style is not None:
            _set_missing(text_style, "fontFamily", FONT_FAMILY)
            _set_missing(text_style, "fontSize", 13)
            if dark:
                _set_missing(text_style, "color", tone_for(True)["tooltip_text"])

        if str(tooltip.get("trigger") or "").lower() == "axis":
            axis_pointer = _ensure_dict(tooltip, "axisPointer")
            if axis_pointer is not None:
                if trigger_custom:
                    _set_missing(axis_pointer, "type", axis_pointer_type)
                else:
                    axis_pointer["type"] = axis_pointer_type


def _polish_label(
    series: dict[str, Any],
    *,
    series_type: str,
    point_count: int,
    series_count: int,
    dark: bool,
    horizontal_bar: bool,
    stacked: bool,
) -> None:
    label = _ensure_dict(series, "label")
    if label is None:
        return
    if label.get("show") is not True:
        if series_type == "pie" and label.get("show") is False:
            label_line = _ensure_dict(series, "labelLine")
            if label_line is not None:
                _set_missing(label_line, "show", False)
        return

    # 点太多时标签必然重叠：宁可隐藏，靠 tooltip/图例读数
    hide = False
    if series_type == "line" and point_count > 20:
        hide = True
    elif series_type == "bar" and point_count > 20:
        hide = True
    elif series_type == "pie" and point_count > 15:
        hide = True
    elif (
        series_type in {"bar", "line"}
        and series_count > 2
        and point_count > 0
        and series_count * point_count > 20
    ):
        hide = True
    if hide:
        label["show"] = False
        if series_type == "pie":
            label_line = _ensure_dict(series, "labelLine")
            if label_line is not None:
                _set_missing(label_line, "show", False)
        return

    if label.get("position") is None:
        if series_type == "bar":
            if stacked:
                position = "inside"
            else:
                position = "right" if horizontal_bar else "top"
        elif series_type == "line":
            position = "top"
        elif series_type in {"scatter", "effectscatter"}:
            position = "right"
        elif series_type == "pie":
            position = "outside"
        else:
            position = None
        if position:
            label["position"] = position

    if label.get("formatter") is None:
        if series_type == "pie":
            label["formatter"] = "{b}: {d}%"
        elif series_type == "bar" and JsCode is not None:
            label["formatter"] = JsCode(_LABEL_VALUE_JS_HIDE_ZERO)
        elif series_type == "line" and JsCode is not None:
            label["formatter"] = JsCode(_LABEL_VALUE_JS)

    _set_missing(label, "fontFamily", FONT_FAMILY)
    _set_missing(label, "fontSize", 11)
    position = str(label.get("position") or "").lower()
    if position in {"top", "right", "outside", "bottom"} and label.get("color") is None:
        label["color"] = tone_for(dark)["data_label"]

    if series_type == "pie":
        label_line = _ensure_dict(series, "labelLine")
        if label_line is not None:
            _set_missing(label_line, "show", True)


def _polish_series(options: dict[str, Any], *, dark: bool) -> None:
    series_nodes = _series(options)
    series_count = sum(
        1
        for node in series_nodes
        if str(node.get("type") or "").lower() in {"bar", "line", "scatter", "effectscatter"}
    )
    horizontal_bar = _is_horizontal_bar(options)

    for node in series_nodes:
        series_type = str(node.get("type") or "").lower()
        data = node.get("data")
        point_count = len(data) if isinstance(data, (list, tuple)) else 0

        if series_type == "bar":
            if node.get("barWidth") is None:
                _set_missing(node, "barMaxWidth", 42)
            _polish_label(
                node,
                series_type=series_type,
                point_count=point_count,
                series_count=series_count,
                dark=dark,
                horizontal_bar=horizontal_bar,
                stacked=bool(node.get("stack")),
            )
        elif series_type == "line":
            line_style = _ensure_dict(node, "lineStyle")
            if line_style is not None:
                _set_missing(line_style, "width", 2)
            if point_count > 30:
                # pyecharts 默认 showSymbol=True，点多时必须显式关掉
                node["showSymbol"] = False
            _polish_label(
                node,
                series_type=series_type,
                point_count=point_count,
                series_count=series_count,
                dark=dark,
                horizontal_bar=horizontal_bar,
                stacked=False,
            )
        elif series_type in {"scatter", "effectscatter"}:
            _set_missing(node, "symbolSize", 10)
            _polish_label(
                node,
                series_type=series_type,
                point_count=point_count,
                series_count=series_count,
                dark=dark,
                horizontal_bar=horizontal_bar,
                stacked=False,
            )
        elif series_type == "pie":
            legends = list(_iter_dicts(options.get("legend")))
            legend_on_right = any(
                str(node_.get("orient") or "").lower() == "vertical"
                and (
                    node_.get("right") is not None
                    or str(node_.get("left") or "").lower() in {"right", "90%"}
                )
                for node_ in legends
            )
            default_radius = ["0%", "75%"]
            if node.get("radius") is None or node.get("radius") == default_radius:
                node["radius"] = ["30%", "58%"] if legend_on_right else ["32%", "58%"]
            default_center = ["50%", "50%"]
            if node.get("center") is None or node.get("center") == default_center:
                node["center"] = ["45%", "55%"] if legend_on_right else ["50%", "55%"]
            _set_missing(node, "avoidLabelOverlap", True)
            _polish_label(
                node,
                series_type=series_type,
                point_count=point_count,
                series_count=series_count,
                dark=dark,
                horizontal_bar=horizontal_bar,
                stacked=False,
            )


def _is_flat_treemap(node: dict[str, Any]) -> bool:
    """数据只有一层、没有 children 时，面包屑和上层标签都是冗余的。"""
    data = node.get("data")
    if not isinstance(data, list) or not data:
        return False
    return all(
        isinstance(item, dict) and not item.get("children")
        for item in data
    )


def _polish_treemap(options: dict[str, Any], *, dark: bool) -> None:
    """矩形树图：去掉无关的图例/面包屑，给标题留空间，并保证标签可读。

    pyecharts 的 TreeMap 默认把 series 名称画在画布顶部（upperLabel/面包屑），
    单层数据时会和标题/副标题重叠；单 series 图例也只有一个重复项。这里只处理
    单层矩形树图，层级数据仍保留面包屑。
    """
    nodes = [
        node for node in _series(options)
        if str(node.get("type") or "").lower() == "treemap"
    ]
    if not nodes:
        return

    # 只有一张矩形树图时，图例没有信息量；Grid/Page 组合图不动
    if len(_series(options)) == 1:
        for legend in _iter_dicts(options.get("legend")):
            legend["show"] = False

    for node in nodes:
        if node.get("top") is None:
            node["top"] = "14%"
        if node.get("bottom") is None:
            node["bottom"] = "4%"

        label = _ensure_dict(node, "label")
        if label is not None:
            tone = tone_for(dark)
            _set_missing(label, "fontFamily", FONT_FAMILY)
            _set_missing(label, "fontSize", 12)
            if label.get("color") is None:
                # 深色文字 + 浅色描边在黄/粉/蓝/绿块上都比白字清楚
                label["color"] = tone["treemap_label"]
                _set_missing(label, "textBorderColor", tone["treemap_label_border"])
                _set_missing(label, "textBorderWidth", 2)
            elif str(label.get("color") or "").lower() in {"white", "#fff", "#ffffff"}:
                # 用户显式用白字时，至少补深色描边保证浅色块可读
                _set_missing(label, "textBorderColor", tone["treemap_label_border_alt"])
                _set_missing(label, "textBorderWidth", 2)

        if not _is_flat_treemap(node):
            continue
        breadcrumb = _ensure_dict(node, "breadcrumb")
        if breadcrumb is not None:
            breadcrumb["show"] = False
        upper_label = _ensure_dict(node, "upperLabel")
        if upper_label is not None:
            upper_label["show"] = False


def polish_options(
    options: dict[str, Any],
    *,
    width: int | float | str | None = None,
    dark: bool = False,
) -> dict[str, Any]:
    """对 pyecharts 的 options dict 做幂等的视觉润色。

    内部先深拷贝（pyecharts 的默认 LabelOpts 等可能跨图共享），完成后写回原 dict，
    因此调用方可以继续使用 ``chart.options``。

    Args:
        options: ``chart.options``（原地更新，但不会污染其他图表的共享默认值）
        width: 图表宽度，支持 ``"900px"`` / 900；缺省按 900 估算
        dark: 是否深色主题（影响文字颜色）

    Returns:
        同一个 options dict，便于链式调用
    """
    if not isinstance(options, dict):
        return options

    # pyecharts 的默认 LabelOpts / SplitLineOpts 等可能被多张图共享，
    # 直接改 opts 会让上一张图的颜色/位置泄漏到下一张图。这里先深拷贝，
    # 润色完再把唯一副本写回原 dict，既保持原地修改语义又不污染共享默认值。
    original = options
    options = copy.deepcopy(options)

    width_px = _parse_width(width)

    # 1. 统一调色板（用户显式 set_colors 时保留）
    if not options.get("color"):
        options["color"] = list(PALETTE)

    series_nodes = _series(options)
    grids = list(_iter_dicts(options.get("grid")))
    multi_grid = len(grids) > 1

    # 2. 标题 / 图例排版
    _polish_title(options, dark=dark, width=width_px, multi_grid=multi_grid)
    _polish_legend(options, dark=dark)
    if _should_move_legend_bottom(options, width=width_px, series=series_nodes):
        legends = list(_iter_dicts(options.get("legend")))
        if legends:
            legend = legends[0]
            legend["top"] = None
            legend["bottom"] = "2%"
            legend["left"] = "center"
            legend["right"] = None
            legend["orient"] = "horizontal"

    # 3. 坐标轴 / 布局 / tooltip / series
    # 先把同位置叠加的 Grid 子图合并成一套坐标轴，再计算标签旋转/边距
    _polish_overlay_grid(options)
    # 多折线只给部分系列加面积会失衡；先统一，再决定数值轴是否贴合数据范围
    _normalize_mixed_area(options)
    # 先把类目标签旋转和 x 轴名称定下来，_polish_grid 才能据此预留底部空间
    _polish_axes(options, dark=dark, width=width_px)
    _polish_grid(options)
    _polish_tooltip(options, dark=dark)
    _polish_series(options, dark=dark)
    _polish_treemap(options, dark=dark)

    original.clear()
    original.update(options)
    return original


def _hex_luminance(color: str) -> float | None:
    """估算 #rgb/#rrggbb 颜色的相对亮度（0 黑 ~ 1 白），非法颜色返回 None。"""
    text = str(color or "").strip().lower()
    match = re.fullmatch(r"#([0-9a-f]{3}|[0-9a-f]{6})", text)
    if not match:
        return None
    hex_part = match.group(1)
    if len(hex_part) == 3:
        hex_part = "".join(ch * 2 for ch in hex_part)
    r, g, b = (int(hex_part[i : i + 2], 16) for i in (0, 2, 4))
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0


def _bg_is_dark(options: dict[str, Any]) -> bool:
    """深色背景检测：覆盖 set_dark_mode() 等不改 theme 属性的暗色来源。"""
    luminance = _hex_luminance(str(options.get("backgroundColor") or ""))
    return luminance is not None and luminance < 0.35


def polish_chart(chart: Any) -> bool:
    """在 chart.render() 前润色 ``chart.options``。

    Returns:
        True 表示本次执行了润色；同一 chart 重复 render 时返回 False。
    """
    if getattr(chart, "_datavis_polished", False):
        return False
    options = getattr(chart, "options", None)
    if not isinstance(options, dict):
        return False

    theme = str(getattr(chart, "theme", "") or "").lower()
    dark = "dark" in theme or _bg_is_dark(options)
    polish_options(
        options,
        width=getattr(chart, "width", None),
        dark=dark,
    )
    try:
        setattr(chart, "_datavis_polished", True)
    except Exception:
        pass
    return True
