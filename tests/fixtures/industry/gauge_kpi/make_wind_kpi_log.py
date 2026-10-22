"""生成 gauge-kpi 场景的真实风电场月度考核 fixture（一次性，产物提交入库）。

按 docs/行业场景扩展规划.md §4.1 规范：
- 这是风电场考核系统导出的月度机组考核表，一行 = 一台机组一条考核记录；
- 完成率不存在于数据里：唯一可用口径 = 本月发电量 / 目标发电量（考核系统谁发谁有），
  聚合/换算由生成代码完成；
- 行业原生列名（机组编号/装机容量/本月发电量/目标发电量/停机时长）；
- 编号列是 0 前缀字符串（考验 normalize 不当数字转）、带千分位数值列；
- GBK 编码（考核系统导出常态）。
"""
from pathlib import Path

OUT = Path(__file__).resolve().parent / "wind_kpi_log.csv"

# (机组编号, 装机容量, 本月发电量, 目标发电量, 停机时长)
# 设计：03 机组完成率 96%（差一点点，考核场景常态）；其他分布在 90%~107%
ROWS = [
    ("01", 2.5, "1,986", 2000, 12.5),
    ("02", 2.5, "2,145", 2100, 8),
    ("03", 2.5, "1,824", 1900, 96),
    ("04", 3.0, "2,388", 2350, 5),
    ("05", 3.0, "2,204", 2300, 22),
    ("06", 2.5, "1,911", 1950, 14),
    ("07", 2.5, "2,078", 2000, 10),
    ("08", 3.0, "2,405", 2250, 3),
]

import csv

# 千分位数值是真实考核系统导出的常态，必须带引号写出（否则被拆列）
with OUT.open("w", encoding="gbk", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["机组编号", "装机容量(MW)", "本月发电量(万kWh)", "目标发电量(万kWh)", "停机时长(h)"])
    for unit, capacity, actual, target, downtime in ROWS:
        writer.writerow([unit, capacity, actual, target, downtime])

# 输出验收基准（README 断言用）
import pandas as pd

df = pd.read_csv(OUT, encoding="gbk")
df["本月发电量(万kWh)"] = (
    df["本月发电量(万kWh)"].astype(str).str.replace(",", "", regex=False).astype(float)
)
rate = (df["本月发电量(万kWh)"] / df["目标发电量(万kWh)"] * 100).round(1)
print("完成率基准：")
for unit, r in zip(df["机组编号"], rate):
    print(f"  {unit}: {r}%")
print("W03 = ", rate.iloc[2], "%")
