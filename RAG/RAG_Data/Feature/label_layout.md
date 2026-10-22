# labelLayout 标签防重叠

数据点密集时（>20 个点、或多系列挤在同一区域），数据标签互相压盖。
`labelLayout` 是 series 级的标签布局控制，`hideOverlap: true` 让 ECharts
自动隐藏互相重叠的标签，交互聚焦时再显示完整。

## 代码示例

```python
from pyecharts import options as opts
from pyecharts.charts import Line

chart = (
    Line()
    .add_xaxis(["%d月" % m for m in range(1, 25)])
    .add_yaxis("销售额", [i * 3 + 100 for i in range(24)], is_symbol_show=False)
    .set_global_opts(title_opts=opts.TitleOpts(title="近两年月度销售额"))
    # set_series_opts 直通 series 级任意 ECharts 选项
    .set_series_opts(
        labelLayout={"hideOverlap": True},
        label_opts=opts.LabelOpts(is_show=True),
    )
)
chart.render()
```

## 要点

- `labelLayout` 用 `set_series_opts(labelLayout={"hideOverlap": True})` 注入；
  它不是 opts 类，直接传 dict；
- 与密集标签自动隐藏策略不同：`hideOverlap` 是**逐对判断真实几何重叠**，
  不牺牲"想显示的标签"，比按点数硬关标签更聪明；
- 类别标签重叠应调 axisLabel 旋转，数据标签重叠才用 labelLayout；
- markLine 等富信息标签更密集时同样受益。

## universalTransition 系列切换动画（同图交互增强）

```python
chart.set_series_opts(universalTransition={"enabled": True})
```

启用后 series 更新（图例切换、dataZoom）时数据点以动画平滑过渡，
对多系列趋势图 + 图例筛选的交互有明显提升。只在直角坐标系系列上使用；
开启后 tooltip 仍走 axis 联动模式即可。
