"""构造 sqlite 样本库供 M2 测试。

3 张表：
- sales   （2024 全年销售明细，1000 行）
- products（产品清单，10 行）
- regions （地区清单，5 行）
"""

import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path


DB_PATH = Path(__file__).resolve().parent / "sample.db"


def build_sample_db():
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE products (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        category TEXT NOT NULL,
        unit_price REAL NOT NULL
    )
    """)
    cur.execute("""
    CREATE TABLE regions (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        manager TEXT NOT NULL
    )
    """)
    cur.execute("""
    CREATE TABLE sales (
        id INTEGER PRIMARY KEY,
        date DATE NOT NULL,
        product_id INTEGER NOT NULL,
        region_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL,
        amount REAL NOT NULL,
        FOREIGN KEY(product_id) REFERENCES products(id),
        FOREIGN KEY(region_id) REFERENCES regions(id)
    )
    """)

    products = [
        (1, "智能手表 A1", "智能硬件", 899.0),
        (2, "笔记本 X15", "智能硬件", 5999.0),
        (3, "蓝牙耳机", "智能硬件", 399.0),
        (4, "CRM 订阅", "软件服务", 1200.0),
        (5, "OA 系统",   "软件服务", 3600.0),
        (6, "云主机基础版", "云计算", 199.0),
        (7, "云主机专业版", "云计算", 899.0),
        (8, "数据仓库",   "云计算", 2499.0),
        (9, "战略咨询",   "咨询业务", 15000.0),
        (10, "IT 顾问",  "咨询业务", 8000.0),
    ]
    regions = [
        (1, "华北", "张伟"),
        (2, "华东", "李娜"),
        (3, "华南", "王强"),
        (4, "西南", "刘洋"),
        (5, "西北", "陈静"),
    ]

    cur.executemany("INSERT INTO products VALUES (?, ?, ?, ?)", products)
    cur.executemany("INSERT INTO regions VALUES (?, ?, ?)", regions)

    # 生成 2024 全年销售明细
    random.seed(42)
    start = date(2024, 1, 1)
    end = date(2024, 12, 31)
    days = (end - start).days + 1

    rows = []
    sid = 1
    for _ in range(1000):
        d = start + timedelta(days=random.randrange(days))
        p = random.choice(products)
        r = random.choice(regions)
        qty = random.randint(1, 20)
        amount = round(qty * p[3] * random.uniform(0.85, 1.05), 2)
        rows.append((sid, d.isoformat(), p[0], r[0], qty, amount))
        sid += 1

    cur.executemany("INSERT INTO sales VALUES (?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()
    print(f"✅ sqlite 样本库已生成: {DB_PATH}")
    print(f"   products: {len(products)} 行")
    print(f"   regions:  {len(regions)} 行")
    print(f"   sales:    {len(rows)} 行")


if __name__ == "__main__":
    build_sample_db()
