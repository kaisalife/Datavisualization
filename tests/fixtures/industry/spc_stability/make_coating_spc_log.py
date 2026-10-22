"""生成 spc-stability 场景 fixture：锂电池极片涂布面密度连续 30 卷记录。

按 docs/行业场景扩展规划.md §4.1 规范：

- 行粒度 = 一卷（业务系统连续测量记录），不是聚合后的两列表；
- 行业原生列名（记录时间/产线/面密度/规格上下限/操作员/换卷备注）；
- 真实特征：一次换卷后刮刀磨损导致均值漂移（特殊原因），随后恢复；
  一个缺失值（"—"）、合计无关的恒定规格列、占位符备注；
- GBK 编码（MES 导出常态）。

脚本同时打印验收基准（均值 / 移动极差 / 3σ 控制限 / 超限点），README 与测试用。
"""
from __future__ import annotations

import csv
from pathlib import Path

OUT = Path(__file__).resolve().parent / "coating_thickness.csv"

# 面密度（mg/cm2）：目标 20.0，正常波动 ±0.03；第 21–25 卷换卷后漂移
VALUES = [
    20.02, 19.98, 20.05, 20.01, 19.96, 20.03, 19.99, "—", 20.04, 20.00,
    19.97, 20.02, 20.06, 19.95, 20.01, 20.03, 19.99, 20.04, 20.02, 20.00,
    20.07, 20.12, 20.18, 20.23, 20.20, 20.15, 20.02, 19.99, 20.03, 20.01,
]
OPERATORS = ["张伟", "李娜", "王强"]
REMARKS = {21: "换卷", 22: "换卷后首检", 25: "复测正常"}

rows = []
for index, value in enumerate(VALUES, start=1):
    day = index  # 2026-09-01 .. 2026-09-30
    rows.append(
        {
            "记录时间": f"2026-09-{day:02d}",
            "产线": "涂布一线",
            "面密度(mg/cm2)": value,
            "规格下限(mg/cm2)": 19.4,
            "规格上限(mg/cm2)": 20.6,
            "操作员": OPERATORS[index % len(OPERATORS)],
            "换卷备注": REMARKS.get(index, "—"),
        }
    )

with OUT.open("w", encoding="gbk", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)


def compute_baseline() -> dict:
    """按技能正文的 X-MR 口径算基准（与生成代码必须一致）。"""
    values = [float(v) for v in VALUES if v != "—"]
    n = len(values)
    center = sum(values) / n
    moving_ranges = [abs(values[i] - values[i - 1]) for i in range(1, n)]
    mr_bar = sum(moving_ranges) / len(moving_ranges)
    sigma = mr_bar / 1.128
    ucl = center + 3 * sigma
    lcl = center - 3 * sigma
    above = [v for v in values if v > ucl]
    below = [v for v in values if v < lcl]
    spec_above = [v for v in values if v > 20.6]
    spec_below = [v for v in values if v < 19.4]
    return {
        "n": n,
        "center": center,
        "mr_bar": mr_bar,
        "sigma": sigma,
        "ucl": ucl,
        "lcl": lcl,
        "above": above,
        "below": below,
        "spec_above": spec_above,
        "spec_below": spec_below,
    }


if __name__ == "__main__":
    baseline = compute_baseline()
    print(f"rows={len(rows)} valid={baseline['n']}")
    print(f"center={baseline['center']:.4f}")
    print(f"mr_bar={baseline['mr_bar']:.4f}")
    print(f"sigma={baseline['sigma']:.4f}")
    print(f"UCL={baseline['ucl']:.4f} LCL={baseline['lcl']:.4f}")
    print(f"above UCL={len(baseline['above'])} {baseline['above']}")
    print(f"below LCL={len(baseline['below'])} {baseline['below']}")
    print(f"over USL={len(baseline['spec_above'])} {baseline['spec_above']}")
    print(f"under LSL={len(baseline['spec_below'])} {baseline['spec_below']}")
