from datetime import datetime, timedelta
from decimal import Decimal

from ..db.connection import connect
from . import parties, treasury
from .errors import ValidationError
from .money import fmt_money, fmt_qty, milli_cents_to_cents, mul_qty_price

_BAL = "(SELECT product_id, SUM(qty_m) AS q FROM stock_movements GROUP BY product_id)"


def _sum(conn, sql, args=()):
    return milli_cents_to_cents(conn.execute(sql, args).fetchone()[0] or 0)


def dashboard(conn, today=None):
    today = today or datetime.now().strftime("%Y-%m-%d")
    month = today[:7]

    def sales(prefix):
        like = prefix + "%"
        total = _sum(conn, "SELECT SUM(-qty_m*unit_price_c) FROM stock_movements WHERE kind IN ('sale','sale_return') AND created_at LIKE ?", (like,))
        profit = _sum(conn, "SELECT SUM(-qty_m*(unit_price_c-unit_cost_c)) FROM stock_movements "
                            "WHERE kind IN ('sale','sale_return') AND created_at LIKE ?", (like,))
        bought = _sum(conn, "SELECT SUM(qty_m*unit_price_c) FROM stock_movements WHERE kind IN ('purchase','purchase_return') AND created_at LIKE ?", (like,))
        return total, profit, bought

    ts, tp, tb = sales(today)
    ms, mp, mb = sales(month)
    cv = _sum(conn, f"SELECT SUM(COALESCE(b.q,0)*p.avg_cost_c) FROM products p LEFT JOIN {_BAL} b ON b.product_id=p.id WHERE p.active=1")
    sv = _sum(conn, f"SELECT SUM(COALESCE(b.q,0)*p.sell_price_c) FROM products p LEFT JOIN {_BAL} b ON b.product_id=p.id WHERE p.active=1")
    cnt = conn.execute("SELECT COUNT(*) FROM products WHERE active=1").fetchone()[0]
    low = conn.execute(f"""SELECT p.name, COALESCE(b.q,0) AS q FROM products p LEFT JOIN {_BAL} b ON b.product_id=p.id
                           WHERE p.active=1 AND COALESCE(b.q,0) <= p.min_qty_m ORDER BY p.name""").fetchall()
    return {"ts": ts, "tp": tp, "tb": tb, "ms": ms, "mp": mp, "mb": mb,
            "cv": cv, "sv": sv, "ep": sv - cv, "cnt": cnt, "low": [(r["name"], r["q"]) for r in low]}


# ====================================================================== تقارير قابلة للتصدير
# كل تقرير بيرجع: {"title","subtitle","columns":[(عنوان, نوع)],"rows":[[...]],"summary":[(عنوان, نوع, قيمة)]}
# الأنواع: text | int | money (قروش) | qty (بالألف). نفس الهيكل بيتعرض وبيتصدّر Excel/PDF.

MOVE_LABELS = {"opening": "رصيد افتتاحي", "purchase": "شراء", "sale": "بيع", "purchase_return": "مرتجع شراء",
               "sale_return": "مرتجع بيع", "transfer_in": "تحويل وارد", "transfer_out": "تحويل صادر",
               "adjust": "تسوية"}
INVOICE_LABELS = {"sale": "فاتورة بيع", "sale_return": "مرتجع بيع",
                  "purchase": "فاتورة شراء", "purchase_return": "مرتجع شراء"}
LOW_TEXT, OK_TEXT = "وصل لحد الطلب", "متوفر"


def format_cell(kind, v):
    if v is None or v == "":
        return ""
    if kind == "money":
        return fmt_money(v)
    if kind == "qty":
        return fmt_qty(v)
    return str(v)


def _report(title, subtitle, columns, rows, summary=None):
    return {"title": title, "subtitle": subtitle, "columns": columns, "rows": rows, "summary": summary or []}


def _range(df, dt):
    lo = treasury.parse_date(df, "من تاريخ") if df else None
    hi = treasury.parse_date(dt, "إلى تاريخ") if dt else None
    if lo and hi and lo > hi:
        raise ValidationError("تاريخ البداية بعد تاريخ النهاية")
    return lo, hi


def _bounds(lo, hi):
    """حدود created_at: من بداية يوم lo لحد قبل بداية اليوم اللي بعد hi."""
    a = f"{lo} 00:00:00" if lo else "0000-00-00 00:00:00"
    b = ((datetime.strptime(hi, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d 00:00:00")
         if hi else "9999-12-31 23:59:59")
    return a, b


def _period(lo, hi):
    if lo and hi:
        return f"الفترة: من {lo} إلى {hi}"
    if lo:
        return f"الفترة: من {lo}"
    if hi:
        return f"الفترة: حتى {hi}"
    return "كل الفترات"


def stock_report(conn, warehouse_id=None):
    """أرصدة المخزون. من غير مخزن محدد: عمود لكل مخزن + الإجمالي."""
    prods = conn.execute("SELECT * FROM products WHERE active=1 ORDER BY name").fetchall()
    whs = conn.execute("SELECT id,name FROM warehouses WHERE active=1 ORDER BY id").fetchall()
    bal = {(r["product_id"], r["warehouse_id"]): r["q"] for r in conn.execute(
        "SELECT product_id, warehouse_id, SUM(qty_m) AS q FROM stock_movements GROUP BY product_id, warehouse_id")}
    if warehouse_id is not None:
        shown = [w for w in whs if w["id"] == warehouse_id]
        if not shown:
            raise ValidationError("المخزن غير موجود")
        sub = f"المخزن: {shown[0]['name']}"
    else:
        shown, sub = whs, "كل المخازن"
    cols = [("الصنف", "text")]
    if warehouse_id is None:
        cols += [(w["name"], "qty") for w in shown]
        cols.append(("الإجمالي", "qty"))
    else:
        cols.append(("الكمية", "qty"))
    cols += [("حد التنبيه", "qty"), ("الحالة", "text"), ("القيمة بالتكلفة", "money"), ("القيمة بسعر البيع", "money")]
    rows, low, cost_total, sell_total = [], 0, 0, 0
    for p in prods:
        per = [bal.get((p["id"], w["id"]), 0) for w in shown]
        qty = sum(per)
        is_low = qty <= p["min_qty_m"]
        low += is_low
        cv, sv = mul_qty_price(qty, p["avg_cost_c"]), mul_qty_price(qty, p["sell_price_c"])
        cost_total, sell_total = cost_total + cv, sell_total + sv
        rows.append([p["name"]] + (per if warehouse_id is None else []) + [qty, p["min_qty_m"],
                     LOW_TEXT if is_low else OK_TEXT, cv, sv])
    return _report("تقرير المخزون", sub, cols, rows,
                   [("عدد الأصناف", "int", len(prods)), ("أصناف وصلت لحد الطلب", "int", low),
                    ("قيمة المخزون بالتكلفة", "money", cost_total), ("قيمة المخزون بسعر البيع", "money", sell_total)])


def low_stock_report(conn):
    rows = []
    for r in conn.execute(f"""SELECT p.name, p.min_qty_m, COALESCE(b.q,0) AS q FROM products p
                              LEFT JOIN {_BAL} b ON b.product_id=p.id WHERE p.active=1 AND COALESCE(b.q,0) <= p.min_qty_m"""):
        rows.append([r["name"], r["q"], r["min_qty_m"], max(0, r["min_qty_m"] - r["q"])])
    rows.sort(key=lambda x: (-x[3], x[0]))
    return _report("الأصناف اللي وصلت لحد الطلب", "كل المخازن",
                   [("الصنف", "text"), ("الكمية الحالية", "qty"), ("حد التنبيه", "qty"), ("النقص", "qty")], rows,
                   [("عدد الأصناف", "int", len(rows))])


def _invoices_report(conn, kinds, title, party_label, paid_label, df, dt):
    lo, hi = _range(df, dt)
    q = """SELECT i.*, COALESCE(c.name, s.name) AS party_name FROM invoices i
           LEFT JOIN customers c ON i.party_type='customer' AND c.id=i.party_id
           LEFT JOIN suppliers s ON i.party_type='supplier' AND s.id=i.party_id
           WHERE i.status='active' AND i.kind IN (?,?) AND i.invoice_date >= ? AND i.invoice_date <= ?
           ORDER BY i.invoice_date, i.kind, i.number"""
    rows, n, gross, ret, paid, rem = [], 0, 0, 0, 0, 0
    for i in conn.execute(q, (kinds[0], kinds[1], lo or "0000-00-00", hi or "9999-12-31")):
        sign = 1 if i["kind"] == kinds[0] else -1
        t, p = sign * i["total_c"], sign * i["paid_c"]
        n += sign == 1
        gross, ret = (gross + t, ret) if sign == 1 else (gross, ret - t)
        paid, rem = paid + p, rem + (t - p)
        rows.append([i["invoice_date"], i["number"], INVOICE_LABELS[i["kind"]], i["party_name"], t, p, t - p])
    cols = [("التاريخ", "text"), ("الرقم", "int"), ("النوع", "text"), (party_label, "text"),
            ("الإجمالي", "money"), (paid_label, "money"), ("المتبقي", "money")]
    return _report(title, _period(lo, hi), cols, rows,
                   [("عدد الفواتير", "int", n), ("إجمالي الفواتير", "money", gross), ("المرتجعات", "money", ret),
                    ("الصافي", "money", gross - ret), (paid_label + " (صافي)", "money", paid),
                    ("المتبقي (صافي)", "money", rem)])


def sales_report(conn, df=None, dt=None):
    return _invoices_report(conn, ("sale", "sale_return"), "تقرير المبيعات", "العميل", "المحصّل", df, dt)


def purchases_report(conn, df=None, dt=None):
    return _invoices_report(conn, ("purchase", "purchase_return"), "تقرير المشتريات", "المورد", "المدفوع", df, dt)


def profit_report(conn, df=None, dt=None):
    """ربح كل صنف = صافي المبيعات (بعد الخصم والمرتجع) - تكلفة الصنف وقت البيع. قبل المصروفات."""
    lo, hi = _range(df, dt)
    a, b = _bounds(lo, hi)
    rows, tq, trev, tcost = [], 0, 0, 0
    for r in conn.execute("""SELECT p.name, SUM(-m.qty_m) AS q, SUM(-m.qty_m*m.unit_price_c) AS rev,
                                    SUM(-m.qty_m*m.unit_cost_c) AS cost
                             FROM stock_movements m JOIN products p ON p.id=m.product_id
                             WHERE m.kind IN ('sale','sale_return') AND m.created_at >= ? AND m.created_at < ?
                             GROUP BY m.product_id""", (a, b)):
        rev, cost = milli_cents_to_cents(r["rev"]), milli_cents_to_cents(r["cost"])
        profit = rev - cost
        margin = f"{(Decimal(profit) * 100 / Decimal(rev)):.1f}%" if rev else ""
        tq, trev, tcost = tq + r["q"], trev + rev, tcost + cost
        rows.append([r["name"], r["q"], rev, cost, profit, margin])
    rows.sort(key=lambda x: -x[4])
    expenses = conn.execute("""SELECT COALESCE(SUM(amount_c),0) FROM treasury_entries
                               WHERE voided=0 AND kind='payment' AND party_type IS NULL AND ref_type='voucher'
                               AND entry_date >= ? AND entry_date <= ?""", (lo or "0000-00-00", hi or "9999-12-31")).fetchone()[0]
    profit_total = trev - tcost
    cols = [("الصنف", "text"), ("الكمية المباعة (صافي)", "qty"), ("صافي المبيعات", "money"),
            ("التكلفة", "money"), ("الربح", "money"), ("الهامش", "text")]
    return _report("الأرباح التقريبية", _period(lo, hi) + " | قبل المصروفات", cols, rows,
                   [("صافي المبيعات", "money", trev), ("التكلفة", "money", tcost), ("إجمالي الربح", "money", profit_total),
                    ("مصروفات عامة (من الخزينة)", "money", expenses), ("الربح بعد المصروفات", "money", profit_total - expenses)])


def statement_report(conn, party_type, party_id, df=None, dt=None):
    """كشف حساب عميل/مورد بين تاريخين مع رصيد أول المدة ورصيد تراكمي."""
    lo, hi = _range(df, dt)
    a, b = _bounds(lo, hi)
    party = conn.execute(f"SELECT * FROM {parties.TABLES[party_type]} WHERE id=?", (party_id,)).fetchone()
    if not party:
        raise ValidationError("الطرف غير موجود")
    before = conn.execute("SELECT COALESCE(SUM(amount_c),0) FROM party_ledger WHERE party_type=? AND party_id=? "
                          "AND created_at < ?", (party_type, party_id, a)).fetchone()[0]
    opening = party["opening_balance_c"] + before
    running, move = opening, 0
    rows = [[lo or party["created_at"][:10], "رصيد أول المدة", "", None, opening]]
    for e in conn.execute("SELECT * FROM party_ledger WHERE party_type=? AND party_id=? AND created_at >= ? "
                          "AND created_at < ? ORDER BY created_at, id", (party_type, party_id, a, b)):
        running, move = running + e["amount_c"], move + e["amount_c"]
        rows.append([e["created_at"][:10], parties.ENTRY_LABELS[e["entry_type"]], e["note"], e["amount_c"], running])
    who = "العميل" if party_type == "customer" else "المورد"
    hint = "الرصيد الموجب = مبلغ مستحق " + ("على العميل" if party_type == "customer" else "للمورد")
    return _report(f"كشف حساب {who}: {party['name']}", _period(lo, hi) + " | " + hint,
                   [("التاريخ", "text"), ("البيان", "text"), ("التفاصيل", "text"), ("المبلغ", "money"),
                    ("الرصيد", "money")], rows,
                   [("رصيد أول المدة", "money", opening), ("حركة الفترة", "money", move),
                    ("الرصيد في آخر المدة", "money", running)])


def product_movement_report(conn, product_id, warehouse_id=None, df=None, dt=None):
    prod = conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
    if not prod:
        raise ValidationError("الصنف غير موجود")
    lo, hi = _range(df, dt)
    a, b = _bounds(lo, hi)
    wh_sql, wh_args, wh_name = "", (), "كل المخازن"
    if warehouse_id is not None:
        w = conn.execute("SELECT name FROM warehouses WHERE id=?", (warehouse_id,)).fetchone()
        if not w:
            raise ValidationError("المخزن غير موجود")
        wh_sql, wh_args, wh_name = " AND m.warehouse_id=?", (warehouse_id,), w[0]
    opening = conn.execute("SELECT COALESCE(SUM(m.qty_m),0) FROM stock_movements m WHERE m.product_id=? AND "
                           "m.created_at < ?" + wh_sql, (product_id, a) + wh_args).fetchone()[0]
    running, tin, tout = opening, 0, 0
    rows = [["", "", "رصيد أول المدة", "", None, None, opening]]
    for m in conn.execute("""SELECT m.*, w.name AS wh FROM stock_movements m JOIN warehouses w ON w.id=m.warehouse_id
                             WHERE m.product_id=? AND m.created_at >= ? AND m.created_at < ?""" + wh_sql +
                          " ORDER BY m.created_at, m.id", (product_id, a, b) + wh_args):
        i, o = (m["qty_m"], 0) if m["qty_m"] > 0 else (0, -m["qty_m"])
        running, tin, tout = running + m["qty_m"], tin + i, tout + o
        rows.append([m["created_at"][:16], m["wh"], MOVE_LABELS[m["kind"]], m["note"], i or None, o or None, running])
    return _report(f"حركة الصنف: {prod['name']}", f"{wh_name} | {_period(lo, hi)}",
                   [("التاريخ", "text"), ("المخزن", "text"), ("النوع", "text"), ("البيان", "text"),
                    ("وارد", "qty"), ("صادر", "qty"), ("الرصيد", "qty")], rows,
                   [("رصيد أول المدة", "qty", opening), ("إجمالي الوارد", "qty", tin),
                    ("إجمالي الصادر", "qty", tout), ("رصيد آخر المدة", "qty", running)])


def treasury_report(conn, df=None, dt=None):
    st = treasury.statement(conn, df, dt)
    lo, hi = _range(df, dt)
    rows = [["", "رصيد أول المدة", "", None, None, st["opening_c"]]]
    rows += [[r["date"], r["label"], r["text"], r["in_c"] or None, r["out_c"] or None, r["running_c"]]
             for r in st["rows"]]
    return _report("حركة الخزينة", _period(lo, hi),
                   [("التاريخ", "text"), ("النوع", "text"), ("البيان", "text"), ("وارد", "money"),
                    ("صادر", "money"), ("الرصيد", "money")], rows,
                   [("رصيد أول المدة", "money", st["opening_c"]), ("إجمالي الوارد", "money", st["total_in"]),
                    ("إجمالي الصادر", "money", st["total_out"]), ("رصيد آخر المدة", "money", st["closing_c"])])


# مفتاح التقرير، عنوانه، والمعاملات اللي بيحتاجها (الواجهة بتظهر خانات المعاملات دي بس)
REPORTS = [
    ("stock", "تقرير المخزون (لكل مخزن)", ("warehouse",)),
    ("low", "الأصناف اللي وصلت لحد الطلب", ()),
    ("sales", "تقرير المبيعات", ("dates",)),
    ("purchases", "تقرير المشتريات", ("dates",)),
    ("profit", "الأرباح التقريبية", ("dates",)),
    ("customer_statement", "كشف حساب عميل", ("customer", "dates")),
    ("supplier_statement", "كشف حساب مورد", ("supplier", "dates")),
    ("product_movement", "حركة صنف", ("product", "warehouse", "dates")),
    ("treasury", "حركة الخزينة", ("dates",)),
]


def build_report(conn, key, params=None):
    p = params or {}
    df, dt = p.get("date_from"), p.get("date_to")
    if key == "stock":
        return stock_report(conn, p.get("warehouse_id"))
    if key == "low":
        return low_stock_report(conn)
    if key == "sales":
        return sales_report(conn, df, dt)
    if key == "purchases":
        return purchases_report(conn, df, dt)
    if key == "profit":
        return profit_report(conn, df, dt)
    if key == "customer_statement":
        if p.get("customer_id") is None:
            raise ValidationError("اختر العميل")
        return statement_report(conn, "customer", p["customer_id"], df, dt)
    if key == "supplier_statement":
        if p.get("supplier_id") is None:
            raise ValidationError("اختر المورد")
        return statement_report(conn, "supplier", p["supplier_id"], df, dt)
    if key == "product_movement":
        if p.get("product_id") is None:
            raise ValidationError("اختر الصنف")
        return product_movement_report(conn, p["product_id"], p.get("warehouse_id"), df, dt)
    if key == "treasury":
        return treasury_report(conn, df, dt)
    raise ValueError(key)


def run_report(db_path, key, params=None):
    """بيفتح اتصال خاص بيه، فينفع يتنادى من thread تاني من غير ما يعطّل الواجهة."""
    conn = connect(db_path)
    try:
        return build_report(conn, key, params)
    finally:
        conn.close()
