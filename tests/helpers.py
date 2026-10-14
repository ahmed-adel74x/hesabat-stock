import os, sqlite3, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

LEGACY_SQL = """
CREATE TABLE products(id INTEGER PRIMARY KEY, name TEXT UNIQUE, buy REAL, sell REAL, qty REAL DEFAULT 0, min_qty REAL DEFAULT 0);
CREATE TABLE moves(id INTEGER PRIMARY KEY, pid INTEGER, kind TEXT, qty REAL, price REAL, cost REAL, date TEXT);
"""


def tmp_db():
    d = tempfile.mkdtemp()
    return os.path.join(d, "stock.db")


def make_legacy(path, bad_kind=False):
    c = sqlite3.connect(path)
    c.executescript(LEGACY_SQL)
    c.executemany("INSERT INTO products VALUES(?,?,?,?,?,?)", [
        (1, "سكر", 12.5, 15.0, 40, 10),
        (2, "زيت", 30.1, 35.55, 3.5, 5),       # كمية وأسعار عشرية
        (4, "رز", 20, 25, -2, 2),                # رصيد سالب
        (5, "شاي", 7.333, 9.999, 0, 0),          # سعر بـ 3 خانات
    ])
    c.executemany("INSERT INTO moves VALUES(?,?,?,?,?,?,?)", [
        (1, 1, "purchase", 50, 12.5, 12.5, "2026-09-01 10:00"),
        (2, 1, "sale", 10, 15.0, 12.5, "2026-09-02 11:30"),
        (3, 2, "sale", 1.5, 35.55, 30.1, "2026-10-01 09:15"),
        (4, 4, "sale", 2, 25, 20, "2026-10-02 09:15"),
        (5, 99, "sale", 3, 8.5, 5, "2026-10-03 12:00"),   # صنف اتحذف
        (6, 99, "purchase", 5, 5, 5, "2026-10-03 11:00"),
    ] + ([(7, 1, bad_kind if isinstance(bad_kind, str) else "xyz", 1, 1, 1, "2026-10-04 10:00")] if bad_kind else []))
    c.commit(); c.close()


def make_v1(path):
    """قاعدة بنفس هيكل النسخة 1 (زي اللي على جهازك دلوقتي) ومعاها بيانات."""
    from hesabat.db.connection import connect
    from hesabat.db.schema import V1_STATEMENTS
    c = connect(path)
    for st in V1_STATEMENTS:
        c.execute(st)
    c.execute("INSERT INTO warehouses(id,name,created_at) VALUES(1,'المخزن الرئيسي','2026-10-01 00:00:00')")
    c.execute("INSERT INTO customers(id,name,is_default,created_at) VALUES(1,'عميل نقدي',1,'2026-10-01 00:00:00')")
    c.execute("INSERT INTO products(id,name,sell_price_c,buy_price_c,avg_cost_c,created_at) VALUES(1,'سكر',1500,1000,1000,'x')")
    c.execute("INSERT INTO stock_movements(product_id,warehouse_id,kind,qty_m,created_at) VALUES(1,1,'opening',5000,'x')")
    c.execute("PRAGMA user_version = 1")
    c.close()
