# dataZoom 数据缩放（长序列浏览）

点数多（>30 个）的时序图，用 dataZoom 让用户在完整趋势与局部细节之间切换，
不需要提前在服务端聚合掉细节。

## 代码示例

```python
from pyecharts import options as opts
from pyecharts.charts import Line

chart = (
    Line()
    .add_xaxis(["%d日" % d for d in range(1, 91)])
    .add_yaxis("销量", [i % 30 + 40 for i in range(90)])
    .set_global_opts(
        title_opts=opts.TitleOpts(title="近 90 天销量"),
        datazoom_opts=[
            # 滑块型：放在底部，直观拖动
            opts.DataZoomOpts(type_="slider", range_start=0, range_end=100),
            # 内置型：滚轮/双指缩放，不占版面
            opts.DataZoomOpts(type_="inside"),
        ],
    )
)
chart.render()
```

## 要点

- `datazoom_opts` 传**列表**（slider + inside 常组合使用）；
- `type_="slider"` 占底部版面，`type_="inside"` 零占位靠交互；
- 初始视野用 `range_start/range_end`（百分比）；长序列默认（0~100）全览即可；
- dataZoom 与 markLine/markArea 兼容；但 Histogram 不要加 dataZoom（分布图要完整）；
- 点数 ≤30 的图不要加 dataZoom，避免无意义的 UI 负担。
