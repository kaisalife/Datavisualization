import os
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
data_root = os.getenv("RAG_DATA_ROOT", str(_PROJECT_ROOT / "RAG" / "RAG_Data"))

print("=" * 60)
print("Pyecharts 知识库文件统计")
print("=" * 60)

chart_types = {}
total_files = 0

# 遍历目录
for item in os.listdir(data_root):
    item_path = os.path.join(data_root, item)
    if os.path.isdir(item_path):
        # 统计该目录下的 .md 文件数量
        md_files = [f for f in os.listdir(item_path) if f.endswith('.md')]
        count = len(md_files)
        chart_types[item] = count
        total_files += count

# 按文件数量排序
sorted_charts = sorted(chart_types.items(), key=lambda x: x[1], reverse=True)

print(f"\n共 {len(chart_types)} 种图表类型，总计 {total_files} 个文档\n")

for chart_name, count in sorted_charts:
    print(f"{chart_name:20s} : {count:3d} 个文件")

print("\n" + "=" * 60)
