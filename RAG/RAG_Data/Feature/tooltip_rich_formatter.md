# tooltip 富文本 formatter（JsCode 自定义提示）

默认 tooltip 只显示 `系列名: 数值`。当业务需要**多指标组合、带单位/千分位、
带涨跌箭头或颜色标记**时，用 `JsCode` 包装自定义 formatter 函数。

## 代码示例

```python
from pyecharts import options as opts
from pyecharts.charts import Line
from pyecharts.commons.utils import JsCode

chart = (
    Line()
    .add_xaxis(["1月", "2月", "3月"])
    .add_yaxis(
        "销售额",
        [1200000, 2000000, 1500000],
        tooltip_opts=opts.TooltipOpts(
            trigger="axis",
            # JsCode 里写真正的 JS 函数字符串；参数 params 是当前轴上所有系列的数据
            formatter=JsCode(
                "function(params){"
                "  let html = params[0].axisValue + '<br/>';"
                "  params.forEach(p => {"
                "    html += p.marker + p.seriesName + '：'"
                "      + Number(p.value).toLocaleString('zh-CN') + ' 元<br/>';"
                "  });"
                "  return html;"
                "}"
            ),
        ),
    )
    .set_global_opts(title_opts=opts.TitleOpts(title="月度销售额"))
)
chart.render()
```

## 要点

- 复杂 formatter **必须**用 `JsCode(...)` 包装，否则会被 JSON 序列化成
  普通字符串而失效；
- `trigger="axis"` 时 params 是数组（多系列联动）；`trigger="item"` 时是单个对象；
- 千分位用 `Number(v).toLocaleString("zh-CN")`，单位写在业务文本里；
- 涨跌箭头/颜色用 HTML 字符串拼（tooltip 支持 `<br/>` 与基本样式）；
- 项目约定：简单数值格式化不必写 formatter，视觉层会统一加千分位；
  只有**多指标组合或条件变色**才值得自定义。
