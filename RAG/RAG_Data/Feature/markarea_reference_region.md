# markArea 参考区间（旺季 / 波动带 / 对比时段）

在直角坐标系图上叠加一块半透明底色区域，用于表达**时间区间、达标区间、
节假日时段、同比对照期**。比单独两条竖线更能表达"一个时段"语义。

## 使用时机

- 用户提到"某时段 / 区间 / 旺季 / 波动带 / 超过 X 的部分高亮"时考虑；
- 区间不能太多：一张图 1–3 块，超过就换成多图或分页展示；
- 区间底色必须明显淡于数据系列（低饱和 + 透明度），否则盖住数据。

## 代码示例

```python
from pyecharts import options as opts
from pyecharts.charts import Line

chart = (
    Line()
    .add_xaxis(["1月", "2月", "3月", "4月", "5月"])
    .add_yaxis(
        "销售额",
        [120, 200, 150, 180, 90],
        markarea_opts=opts.MarkAreaOpts(
            data=[
                # 类目轴：用 x=(起, 止) 指定区间；数值轴用 y=(下限, 上限)
                opts.MarkAreaItem(name="春节旺季", x=("1月", "2月")),
                opts.MarkAreaItem(name="达标区", y=(150, 200)),
            ],
            itemstyle_opts=opts.ItemStyleOpts(color="#f5deb3", opacity=0.35),
        ),
    )
    .set_global_opts(title_opts=opts.TitleOpts(title="月度销售额与重点时段"))
)
chart.render()
```

## 要点

- `markarea_opts` 挂在 `add_yaxis` 上（series 级），不是全局配置；
- `MarkAreaItem(name=..., x=(起,止))` 适合类目轴时段；`y=(下限,上限)` 画达标带；
- 半透明底色用 `itemstyle_opts=opts.ItemStyleOpts(color=..., opacity=0.3~0.4)`，
  颜色选退出主调色板的浅色（浅黄 / 浅蓝），不要用主题色系；
- 区间 name 显示在区域顶部，过长会被截断，取名 4–8 字；
- markArea 与 markLine 可同时使用（目标线放区间上沿很常见）。
