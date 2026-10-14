"""حركة المخزون. كل رصيد = مجموع stock_movements. كل دالة عملية بتشتغل جوه transaction واحدة."""
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from ..db.connection import tx
from .errors import ValidationError
from .money import parse_money, parse_qty, fmt_qty


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_product(conn, pid):
    row = conn.execute("SELECT * FROM products WHERE id=? AND active=1", (pid,)).fetchone()
    if not row:
        raise ValidationError("الصنف غير موجود")
    return row


def get_warehouse(conn, wid):
    row = conn.execute("SELECT * FROM warehouses WHERE id=? AND active=1", (wid,)).fetchone()
    if not row:
        raise ValidationError("المخزن غير موجود")
    return row


def balance(conn, product_id, warehouse_id=None):
    if warehouse_id is None:
        sql, args = "SELECT COALESCE(SUM(qty_m),0) FROM stock_movements WHERE product_id=?", (product_id,)
    else:
        sql, args = ("SELECT COALESCE(SUM(qty_m),0) FROM stock_movements WHERE product_id=? AND warehouse_id=?",
                     (product_id, warehouse_id))
    return conn.execute(sql, args).fetchone()[0]


def stock_table(conn, warehouse_id):
    """أرصدة كل الأصناف النشطة في مخزن معين."""
    return conn.execute("""
        SELECT p.id, p.name, p.min_qty_m, COALESCE(SUM(m.qty_m),0) AS qty_m
        FROM products p LEFT JOIN stock_movements m ON m.product_id=p.id AND m.warehouse_id=?
        WHERE p.active=1 GROUP BY p.id ORDER BY p.name""", (warehouse_id,)).fetchall()


def add_movement(conn, product_id, warehouse_id, kind, qty_m, unit_price_c=0, unit_cost_c=0,
                 ref_type=None, ref_id=None, note="", created_at=None):
    cur = conn.execute(
        "INSERT INTO stock_movements(product_id,warehouse_id,kind,qty_m,unit_price_c,unit_cost_c,"
        "ref_type,ref_id,note,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (product_id, warehouse_id, kind, qty_m, unit_price_c, unit_cost_c, ref_type, ref_id, note,
         created_at or now_str()))
    return cur.lastrowid


def require_available(conn, product, warehouse, need_m):
    have = balance(conn, product["id"], warehouse["id"])
    if need_m > have:
        raise ValidationError(f"الكمية المتاحة من «{product['name']}» في «{warehouse['name']}» "
                              f"= {fmt_qty(have)} فقط، والمطلوب {fmt_qty(need_m)}")


def new_average_cost(old_total_m, old_avg_c, qty_m, price_c):
    """المتوسط المرجّح بعد الشراء. لو الرصيد القديم صفر أو سالب بيبقى سعر الشراء الجديد."""
    if old_total_m <= 0:
        return price_c
    d = (Decimal(old_total_m) * old_avg_c + Decimal(qty_m) * price_c) / Decimal(old_total_m + qty_m)
    return int(d.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def apply_purchase(conn, product_id, warehouse_id, qty_m, list_price_c, net_unit_c,
                   ref_type=None, ref_id=None, note="", created_at=None):
    """بتزوّد المخزون وتحدّث المتوسط المرجّح. list_price_c = السعر المكتوب (بيبقى آخر سعر شراء)،
    net_unit_c = السعر الفعلي بعد توزيع الخصم (هو اللي بيدخل في المتوسط وفي حركة المخزن)."""
    prod = get_product(conn, product_id)
    avg = new_average_cost(balance(conn, product_id), prod["avg_cost_c"], qty_m, net_unit_c)
    conn.execute("UPDATE products SET avg_cost_c=?, buy_price_c=? WHERE id=?", (avg, list_price_c, product_id))
    # unit_cost_c في حركة الشراء = المتوسط الجديد وقت العملية
    return add_movement(conn, product_id, warehouse_id, "purchase", qty_m, net_unit_c, avg,
                        ref_type, ref_id, note, created_at)


def record_purchase(conn, product_id, warehouse_id, qty, price=None, note="", ref_type=None, ref_id=None):
    q = parse_qty(qty)
    with tx(conn):
        prod, wh = get_product(conn, product_id), get_warehouse(conn, warehouse_id)
        p = parse_money(price, "السعر") if price not in (None, "") else prod["buy_price_c"]
        return apply_purchase(conn, product_id, wh["id"], q, p, p, ref_type, ref_id, note)


def record_sale(conn, product_id, warehouse_id, qty, price=None, note="", ref_type=None, ref_id=None):
    q = parse_qty(qty)
    with tx(conn):
        prod, wh = get_product(conn, product_id), get_warehouse(conn, warehouse_id)
        p = parse_money(price, "السعر") if price not in (None, "") else prod["sell_price_c"]
        require_available(conn, prod, wh, q)
        # بنسجّل تكلفة الصنف وقت البيع، فأرباح العمليات القديمة مبتتغيرش لما أسعار الشراء تتغير
        return add_movement(conn, product_id, wh["id"], "sale", -q, p, prod["avg_cost_c"], ref_type, ref_id, note)


def transfer(conn, from_wh, to_wh, items, note=""):
    """items: قائمة (product_id, qty). بترجع رقم التحويل."""
    if from_wh == to_wh:
        raise ValidationError("المخزن المصدر والوجهة لازم يكونوا مختلفين")
    if not items:
        raise ValidationError("اختر صنف واحد على الأقل")
    agg = {}
    for pid, qty in items:
        agg[pid] = agg.get(pid, 0) + parse_qty(qty)
    with tx(conn):
        src, dst = get_warehouse(conn, from_wh), get_warehouse(conn, to_wh)
        tid = conn.execute("INSERT INTO stock_transfers(from_wh,to_wh,note,created_at) VALUES(?,?,?,?)",
                           (from_wh, to_wh, note, now_str())).lastrowid
        for pid, q in agg.items():
            prod = get_product(conn, pid)
            require_available(conn, prod, src, q)
            add_movement(conn, pid, from_wh, "transfer_out", -q, 0, prod["avg_cost_c"], "transfer", tid, note)
            add_movement(conn, pid, to_wh, "transfer_in", q, 0, prod["avg_cost_c"], "transfer", tid, note)
        return tid


def apply_stocktake(conn, warehouse_id, counts, note=""):
    """counts: {product_id: الكمية الفعلية}. الفروق بتتسوّى بحركات adjust. بترجع (رقم الجرد, عدد الأصناف اللي اتعدلت)."""
    parsed = {pid: parse_qty(v, "الرصيد الفعلي", allow_zero=True) for pid, v in counts.items()
              if str(v).strip() != ""}
    if not parsed:
        raise ValidationError("اكتب الرصيد الفعلي لصنف واحد على الأقل")
    with tx(conn):
        wh = get_warehouse(conn, warehouse_id)
        sid = conn.execute("INSERT INTO stocktakes(warehouse_id,note,created_at) VALUES(?,?,?)",
                           (wh["id"], note, now_str())).lastrowid
        changed = 0
        for pid, counted in parsed.items():
            prod = get_product(conn, pid)
            system = balance(conn, pid, wh["id"])
            diff = counted - system
            conn.execute("INSERT INTO stocktake_items(stocktake_id,product_id,system_qty_m,counted_qty_m,diff_qty_m) "
                         "VALUES(?,?,?,?,?)", (sid, pid, system, counted, diff))
            if diff:
                add_movement(conn, pid, wh["id"], "adjust", diff, 0, prod["avg_cost_c"], "stocktake", sid, "تسوية جرد")
                changed += 1
        return sid, changed
