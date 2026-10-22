"""生成 pareto 质量场景的真实 MES 导出 fixture（一次性，产物提交入库）。

按 docs/行业场景扩展规划.md §4.1 规范：
- 行粒度 = 每笔不良记录（事件），聚合由生成代码自己做；
- 列名行业原生词（发生日期/不良描述/判定数量/批次号/备注）；
- 长尾分布（前 2 项占 ~53%）、同义类目（划伤 vs 表面划伤）、冗余列（备注含 — 占位）；
- GBK 编码（机房 MES 导出常态，走 CSV 编码探测）。
"""
from pathlib import Path

OUT = Path(__file__).resolve().parent / "defect_log.csv"

# (不良描述, [每笔数量]) —— 分布手工设计：焊点虚焊+元件偏移 占总数过半
DEFECT_ROWS: dict[str, list[int]] = {
    "焊点虚焊": [3, 2, 1, 4, 2, 3, 1, 2, 5, 2, 3, 1, 2, 2],   # 34
    "元件偏移": [2, 3, 1, 2, 4, 2, 1, 3, 1, 2],               # 21
    "少锡": [2, 1, 3, 2, 1, 2, 2, 1],                          # 14
    "立碑": [2, 1, 3, 1, 2],                                   # 9
    "连锡": [1, 3, 2, 1, 2],                                   # 9
    "桥接短路": [3, 4],                                        # 7
    "划伤": [2, 2],                                            # 4
    "表面划伤": [1, 1],                                        # 2（同义类目，考验不臆造合并）
    "锡珠": [1], "异物": [1], "端子变形": [1],                 # 零星期
}

DATES = [  # 两周工作日（周一~周五），避开周末
    "2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11",
    "2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18",
]
# QC 备注要够真实（多种检查/复判短语），否则拆分器会把它当低基数维度透射
NOTES = [
    "—", "返修后恢复", "已复判", "待评审", "客户让步放行", "外观检查通过",
    "需工艺评审", "复判OK", "原因待查", "留样观察", "超出规格", "返工完成",
    "—", "已复判", "返修后恢复", "待评审", "外观检查通过", "—",
    "复判OK", "返工完成", "原因待查", "已复判", "返修后恢复", "留样观察",
    "—", "待评审", "返工完成", "客户让步放行", "已复判", "—",
    "复判OK", "返修后恢复", "外观检查通过", "留样观察", "待评审", "已复判",
    "—", "返工完成", "原因待查", "返修后恢复", "复判OK", "已复判",
    "外观检查通过", "—", "待评审", "返修后恢复", "已复判", "复判OK",
    "留样观察", "返工完成", "已复判",
]

rows: list[str] = ["发生日期,不良描述,判定数量,批次号,备注"]

def _flatten():
    """把缺陷清单摊平成逐笔记录：数量列表每个元素是一笔。"""
    flat: list[tuple[str, int]] = []
    for defect, quantities in DEFECT_ROWS.items():
        for qty in quantities:
            flat.append((defect, int(qty)))
    return flat


def _assign_dates(flat):
    """按缺陷项分组穿插到工作日：同缺陷尽量分散，不同缺陷交错。"""
    assigned: list[tuple[str, str, int]] = []
    pools = {defect: list(qtys) for defect, qtys in DEFECT_ROWS.items()}
    while any(pools.values()):
        for defect in list(pools):
            if not pools[defect]:
                continue
            qty = pools[defect].pop(0)
            idx = len(assigned)
            date = DATES[idx % len(DATES)]
            assigned.append((date, defect, qty))
    return assigned


flat = _flatten()
assigned = _assign_dates(flat)
for i, (date, defect, qty) in enumerate(assigned):
    batch_no = i + 1
    batch = f"B{date.replace('-', '')}A{batch_no:03d}"
    note = NOTES[i % len(NOTES)] if i < len(NOTES) else "—"
    rows.append(f"{date},{defect},{qty},{batch},{note}")

OUT.write_text("\n".join(rows) + "\n", encoding="gbk")

# 输出验收基准（README 断言用）
import pandas as pd

df = pd.read_csv(OUT, encoding="gbk")
agg = (
    df.groupby("不良描述", as_index=False)["判定数量"].sum()
    .sort_values("判定数量", ascending=False, ignore_index=True)
)
agg["累计占比"] = (agg["判定数量"].cumsum() / agg["判定数量"].sum() * 100).round(2)
print(OUT.read_text(encoding="gbk").splitlines()[0])
print("总笔数:", len(df), "总量:", int(df["判定数量"].sum()), "类目数:", agg["判定数量"].count())
print(agg.to_string(index=False))
