import sqlite3

from ..db.connection import tx
from .errors import ValidationError
from .money import parse_money, parse_qty
from . import inventory
from .search import matches


def _name(name):
    n = (name or "").strip()
    if not n:
        raise ValidationError("اكتب اسم الصنف")
    if len(n) > 120:
        raise ValidationError("اسم الصنف طويل جداً")
    return n


def list_products(conn, query=""):
    """الأصناف النشطة مرتبة برقم الصنف (من 1). query: بحث بالاسم أو برقم الصنف (فاضي = الكل)."""
    rows = conn.execute("""
        SELECT p.*, COALESCE((SELECT SUM(qty_m) FROM stock_movements m WHERE m.product_id=p.id),0) AS qty_m
        FROM products p WHERE p.active=1 ORDER BY p.id""").fetchall()
    if query and query.strip():
        rows = [r for r in rows if matches(query, r["name"], r["id"])]
    return rows


def count(conn):
    return conn.execute("SELECT COUNT(*) FROM products WHERE active=1").fetchone()[0]


def get(conn, pid):
    return inventory.get_product(conn, pid)


def create(conn, name, buy, sell, min_qty="0", opening_qty="0", warehouse_id=None):
    n = _name(name)
    buy_c = parse_money(buy, "سعر الشراء", allow_empty=True)
    sell_c = parse_money(sell, "سعر البيع", allow_empty=True)
    min_m = parse_qty(min_qty, "حد التنبيه", allow_zero=True, allow_empty=True)
    open_m = parse_qty(opening_qty, "الكمية", allow_zero=True, allow_empty=True)
    with tx(conn):
        try:
            pid = conn.execute("INSERT INTO products(name,sell_price_c,buy_price_c,avg_cost_c,min_qty_m,created_at) "
                               "VALUES(?,?,?,?,?,?)", (n, sell_c, buy_c, buy_c, min_m, inventory.now_str())).lastrowid
        except sqlite3.IntegrityError:
            raise ValidationError("الصنف موجود بالفعل (ممكن يكون محذوف سابقاً)")
        if open_m:
            wid = warehouse_id or conn.execute("SELECT MIN(id) FROM warehouses WHERE active=1").fetchone()[0]
            inventory.add_movement(conn, pid, wid, "opening", open_m, buy_c, buy_c, note="رصيد افتتاحي")
        return pid


def update(conn, pid, name, buy, sell, min_qty, qty=None, warehouse_id=None):
    """qty (اختياري): لو اتبعتت الكمية الجديدة في المخزن (الأول لو warehouse_id فاضي) بتتسوّى بحركة adjust.
    فاضية أو None = مبنلمسش المخزون."""
    n = _name(name)
    buy_c = parse_money(buy, "سعر الشراء", allow_empty=True)
    sell_c = parse_money(sell, "سعر البيع", allow_empty=True)
    min_m = parse_qty(min_qty, "حد التنبيه", allow_zero=True, allow_empty=True)
    change_qty = qty is not None and str(qty).strip() != ""
    if change_qty:
        parse_qty(qty, "الكمية", allow_zero=True)       # نتحقق قبل ما نعدّل أي حاجة
    with tx(conn):
        inventory.get_product(conn, pid)
        try:
            conn.execute("UPDATE products SET name=?, buy_price_c=?, sell_price_c=?, min_qty_m=? WHERE id=?",
                         (n, buy_c, sell_c, min_m, pid))
        except sqlite3.IntegrityError:
            raise ValidationError("الاسم مستخدم لصنف آخر")
        if change_qty:
            wid = warehouse_id or conn.execute("SELECT MIN(id) FROM warehouses WHERE active=1").fetchone()[0]
            inventory.set_quantity(conn, pid, wid, qty, "تعديل الكمية من شاشة الأصناف")


def deactivate(conn, pid):
    """الصنف عليه حركات فمبنمسحوش نهائي، بنوقفه (يختفي من القوائم ويفضل في السجل)."""
    with tx(conn):
        inventory.get_product(conn, pid)
        conn.execute("UPDATE products SET active=0 WHERE id=?", (pid,))
