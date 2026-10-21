"""
فواتير الشراء ومرتجع الشراء (والبيع ومرتجعه في المرحلة 4 بنفس الآلية).

عند الحفظ، كله في transaction واحدة:
  1) المخزون: حركات في stock_movements (ref_type='invoice').
  2) حساب الطرف: قيد في party_ledger بإجمالي الفاتورة.
  3) الخزينة: سند بالمدفوع (treasury.add_entry) وده بيسجّل دفعة الطرف في حسابه أوتوماتيك.
التعديل/الإلغاء بيعكس الأثر القديم (حركات عكسية، قيود عكسية، إلغاء سندات الخزينة) بدل ما يمسح التاريخ.

الخصم بيتوزع على الأصناف بنسبة قيمتها، والسعر الفعلي بعد الخصم هو اللي بيدخل في متوسط التكلفة.
تنبيه: إلغاء/تعديل فاتورة شراء قديمة بيعدّل متوسط التكلفة حسابياً (تقريبي لو حصلت مشتريات بعدها).
"""
import html
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from ..db import maintenance
from ..db.connection import tx
from . import inventory, parties, treasury
from .errors import ValidationError
from .money import fmt_money, fmt_qty, mul_qty_price, parse_money, parse_qty

KINDS = {
    "purchase": {"title": "فاتورة شراء", "party": "supplier", "party_label": "المورد",
                 "stock_dir": 1, "ledger": "invoice", "ledger_sign": 1, "cash": "payment", "cash_label": "المدفوع"},
    "purchase_return": {"title": "مرتجع مشتريات", "party": "supplier", "party_label": "المورد",
                        "stock_dir": -1, "ledger": "return", "ledger_sign": -1, "cash": "receipt",
                        "cash_label": "المستلم نقداً"},
    "sale": {"title": "فاتورة بيع", "party": "customer", "party_label": "العميل",
             "stock_dir": -1, "ledger": "invoice", "ledger_sign": 1, "cash": "receipt", "cash_label": "المحصّل",
             "cash_customer_msg": "العميل النقدي لازم يدفع كامل المبلغ. اختر عميل مسجّل لو البيع آجل."},
    "sale_return": {"title": "مرتجع مبيعات", "party": "customer", "party_label": "العميل",
                    "stock_dir": 1, "ledger": "return", "ledger_sign": -1, "cash": "payment",
                    "cash_label": "المردود نقداً",
                    "cash_customer_msg": "لازم ترجّع للعميل النقدي كامل المبلغ. اختر عميل مسجّل لو هتخصمه من حسابه."},
}
_TABLES = {"customer": "customers", "supplier": "suppliers"}


def _div(a, b):
    return int((Decimal(a) / Decimal(b)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _parse_items(items):
    if not items:
        raise ValidationError("أضف صنف واحد على الأقل للفاتورة")
    out = []
    for pid, qty, price in items:
        q, p = parse_qty(qty, "الكمية"), parse_money(price, "السعر")
        out.append((pid, q, p, mul_qty_price(q, p)))
    return out


def preview(items, discount="0", paid="0"):
    """حساب الإجماليات من غير ما يلمس قاعدة البيانات (الواجهة بتستخدمه للعرض)."""
    lines = _parse_items(items)
    sub = sum(l[3] for l in lines)
    d = parse_money(discount, "الخصم", allow_empty=True)
    if d > sub:
        raise ValidationError("الخصم أكبر من إجمالي الفاتورة")
    total = sub - d
    pd = parse_money(paid, "المدفوع", allow_empty=True)
    if pd > total:
        raise ValidationError("المدفوع أكبر من إجمالي الفاتورة")
    return {"line_totals": [l[3] for l in lines], "subtotal_c": sub, "discount_c": d,
            "total_c": total, "paid_c": pd, "remaining_c": total - pd}


def _allocate(discount_c, totals):
    """توزيع الخصم على السطور بنسبة قيمتها (أكبر باقي)، ومجموع الأنصبة = الخصم بالظبط."""
    s = sum(totals)
    if discount_c == 0 or s == 0:
        return [0] * len(totals)
    shares = [discount_c * t // s for t in totals]
    rem = discount_c - sum(shares)
    for i in sorted(range(len(totals)), key=lambda i: (discount_c * totals[i]) % s, reverse=True)[:rem]:
        shares[i] += 1
    return shares


def default_price(conn, kind, product_id):
    p = inventory.get_product(conn, product_id)
    return p["buy_price_c"] if KINDS[kind]["party"] == "supplier" else p["sell_price_c"]


# ---------------------------------------------------------------- أثر المخزون
def _active_effect(conn, invoice_id):
    """صافي أثر الفاتورة الحالي على المخزون (بعد أي تعديلات سابقة): (صنف، مخزن، كمية، قيمة بيع/شراء، قيمة التكلفة)."""
    return conn.execute("""SELECT product_id, warehouse_id, SUM(qty_m) AS q, SUM(qty_m*unit_price_c) AS v,
                                  SUM(qty_m*unit_cost_c) AS cv
                           FROM stock_movements WHERE ref_type='invoice' AND ref_id=?
                           GROUP BY product_id, warehouse_id HAVING SUM(qty_m) <> 0""", (invoice_id,)).fetchall()


def _apply_stock(conn, kind, invoice_id, wh_id, lines, discount_c, label, created):
    shares = _allocate(discount_c, [l[3] for l in lines])
    wh = inventory.get_warehouse(conn, wh_id)
    for (pid, q, price, total), share in zip(lines, shares):
        net_unit = _div((total - share) * 1000, q)  # سعر الوحدة الفعلي بعد الخصم
        prod = inventory.get_product(conn, pid)
        ref = ("invoice", invoice_id, label, created)
        if kind == "purchase":
            inventory.apply_purchase(conn, pid, wh_id, q, price, net_unit, *ref)
        elif kind == "sale_return":      # الكمية بترجع بتكلفة الصنف الحالية
            inventory.add_movement(conn, pid, wh_id, "sale_return", q, net_unit, prod["avg_cost_c"], *ref)
        else:                            # بيع أو مرتجع شراء: بيطلّع كمية فلازم تكون متاحة
            inventory.require_available(conn, prod, wh, q)
            # في البيع بنسجّل تكلفة الصنف وقت العملية عشان الربح ميتغيرش بعدين
            inventory.add_movement(conn, pid, wh_id, kind, -q, net_unit, prod["avg_cost_c"], *ref)


def _reverse_stock(conn, kind, plan, invoice_id, label, created):
    for r in plan:
        pid, wid, q, v, cv = r["product_id"], r["warehouse_id"], r["q"], r["v"], r["cv"]
        prod = conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
        c = _div(v, q)                  # متوسط السعر الفعلي للصنف في الفاتورة
        ref = ("invoice", invoice_id, label, created)
        if kind == "purchase":
            have = inventory.balance(conn, pid, wid)
            if have < q:
                raise ValidationError(f"مينفعش تلغي/تعدّل الفاتورة: الكمية المتاحة من «{prod['name']}» ({fmt_qty(have)}) "
                                      f"أقل من كمية الفاتورة ({fmt_qty(q)}). غالباً اتباع منها.")
            total, avg = inventory.balance(conn, pid), prod["avg_cost_c"]
            if total - q > 0:           # عكس أثر الشراء على المتوسط المرجّح
                avg = max(0, _div(Decimal(total) * avg - Decimal(q) * c, total - q))
                conn.execute("UPDATE products SET avg_cost_c=? WHERE id=?", (avg, pid))
            inventory.add_movement(conn, pid, wid, "purchase", -q, c, avg, *ref)
        elif kind == "purchase_return":
            inventory.add_movement(conn, pid, wid, "purchase_return", -q, c, prod["avg_cost_c"], *ref)
        elif kind == "sale":            # الكمية بترجع بنفس التكلفة اللي اتباعت بيها
            inventory.add_movement(conn, pid, wid, "sale", -q, c, _div(cv, q), *ref)
        else:                           # sale_return
            have = inventory.balance(conn, pid, wid)
            if have < q:
                raise ValidationError(f"مينفعش تلغي/تعدّل المرتجع: الكمية المتاحة من «{prod['name']}» ({fmt_qty(have)}) "
                                      f"أقل من كمية المرتجع ({fmt_qty(q)}). غالباً اتباعت تاني.")
            inventory.add_movement(conn, pid, wid, "sale_return", -q, c, _div(cv, q), *ref)


# ---------------------------------------------------------------- الحفظ والتعديل والإلغاء
def _stamp(d):
    return f"{d} {datetime.now():%H:%M:%S}"


def _get_active(conn, invoice_id, kind=None):
    inv = conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
    if not inv:
        raise ValidationError("الفاتورة غير موجودة")
    if inv["status"] == "cancelled":
        raise ValidationError("الفاتورة ملغية بالفعل")
    if kind and inv["kind"] != kind:
        raise ValidationError("نوع الفاتورة غير مطابق")
    return inv


def _reverse_ledger(conn, inv, k, label):
    if inv["total_c"]:
        parties.add_ledger_entry(conn, inv["party_type"], inv["party_id"], "adjust",
                                 -k["ledger_sign"] * inv["total_c"], "invoice", inv["id"],
                                 "إلغاء/تعديل " + label, _stamp(inv["invoice_date"]))


def _save(conn, kind, invoice_id, party_id, warehouse_id, items, discount, paid, note, invoice_date):
    k = KINDS[kind]
    p = preview(items, discount, paid)
    lines = _parse_items(items)
    d = treasury.past_date(invoice_date) if invoice_date else treasury.today()
    note = (note or "").strip()
    with tx(conn):
        party = parties.get(conn, k["party"], party_id)
        inventory.get_warehouse(conn, warehouse_id)
        if k["party"] == "customer" and party["is_default"] and p["paid_c"] != p["total_c"]:
            raise ValidationError(k["cash_customer_msg"])   # العميل النقدي مبيبقاش عليه رصيد
        now, old, plan = inventory.now_str(), None, None
        if invoice_id is None:
            number = conn.execute("SELECT COALESCE(MAX(number),0)+1 FROM invoices WHERE kind=?", (kind,)).fetchone()[0]
            invoice_id = conn.execute(
                "INSERT INTO invoices(kind,number,party_type,party_id,warehouse_id,invoice_date,subtotal_c,discount_c,"
                "total_c,paid_c,note,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (kind, number, k["party"], party_id, warehouse_id, d, p["subtotal_c"], p["discount_c"],
                 p["total_c"], p["paid_c"], note, now, now)).lastrowid
        else:
            old = _get_active(conn, invoice_id, kind)
            number, plan = old["number"], _active_effect(conn, invoice_id)
            old_label = f"{k['title']} رقم {number}"
            treasury.void_linked(conn, "invoice", invoice_id)       # دفعات الفاتورة القديمة
            _reverse_ledger(conn, old, k, old_label)
            conn.execute("DELETE FROM invoice_items WHERE invoice_id=?", (invoice_id,))
            conn.execute("UPDATE invoices SET party_id=?,warehouse_id=?,invoice_date=?,subtotal_c=?,discount_c=?,"
                         "total_c=?,paid_c=?,note=?,updated_at=? WHERE id=?",
                         (party_id, warehouse_id, d, p["subtotal_c"], p["discount_c"], p["total_c"], p["paid_c"],
                          note, now, invoice_id))
        for (pid, q, price, total) in lines:
            inventory.get_product(conn, pid)
            conn.execute("INSERT INTO invoice_items(invoice_id,product_id,qty_m,unit_price_c,line_total_c) "
                         "VALUES(?,?,?,?,?)", (invoice_id, pid, q, price, total))
        label, created = f"{k['title']} رقم {number}", _stamp(d)

        def apply_new():
            _apply_stock(conn, kind, invoice_id, warehouse_id, lines, p["discount_c"], label, created)

        def reverse_old():
            if plan:
                _reverse_stock(conn, kind, plan, invoice_id, "إلغاء/تعديل " + label, _stamp(old["invoice_date"]))
        # الترتيب بيمنع أخطاء كاذبة: اللي بيزوّد المخزون ندخّله الأول، واللي بينقصه نرجّع القديم الأول
        for step in ((apply_new, reverse_old) if k["stock_dir"] > 0 else (reverse_old, apply_new)):
            step()
        if p["total_c"]:
            parties.add_ledger_entry(conn, k["party"], party_id, k["ledger"], k["ledger_sign"] * p["total_c"],
                                     "invoice", invoice_id, label, created)
        if p["paid_c"]:
            treasury.add_entry(conn, k["cash"], p["paid_c"], k["party"], party_id, note=label,
                               entry_date=d, ref_type="invoice", ref_id=invoice_id)
        return invoice_id


def create_invoice(conn, kind, party_id, warehouse_id, items, discount="0", paid="0", note="", invoice_date=None):
    """items: قائمة (product_id, الكمية, السعر). بترجع رقم الفاتورة (id)."""
    return _save(conn, kind, None, party_id, warehouse_id, items, discount, paid, note, invoice_date)


def update_invoice(conn, invoice_id, party_id, warehouse_id, items, discount="0", paid="0", note="", invoice_date=None):
    kind = _get_active(conn, invoice_id)["kind"]
    return _save(conn, kind, invoice_id, party_id, warehouse_id, items, discount, paid, note, invoice_date)


def cancel_invoice(conn, invoice_id):
    with tx(conn):
        inv = _get_active(conn, invoice_id)
        k = KINDS[inv["kind"]]
        label = f"{k['title']} رقم {inv['number']}"
        plan = _active_effect(conn, invoice_id)
        treasury.void_linked(conn, "invoice", invoice_id)
        _reverse_ledger(conn, inv, k, label)
        _reverse_stock(conn, inv["kind"], plan, invoice_id, "إلغاء " + label, _stamp(inv["invoice_date"]))
        conn.execute("UPDATE invoices SET status='cancelled', updated_at=? WHERE id=?", (inventory.now_str(), invoice_id))


def delete_invoice(conn, invoice_id):
    """بيمسح الفاتورة نهائياً: الأول بيعكس أثرها (مخزون، حساب الطرف، خزينة)، وبعدين بيمسحها هي وكل حركاتها
    فتختفي من القوائم والتقارير وكشوف الحساب. مفيش رجوع. لو مينفعش تتلغي (مثلاً الكمية اتباعت) مبيتمسحش حاجة."""
    with tx(conn):
        cancel_invoice(conn, invoice_id)
        if not maintenance.purge_invoice(conn, invoice_id):
            raise ValidationError("مقدرتش أمسح الفاتورة لأن أثرها المحاسبي مش متعادل. متمسحتش، وابعت الموضوع للمطور.")


# ---------------------------------------------------------------- استعلامات للواجهة
def get_invoice(conn, invoice_id):
    inv = conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
    if not inv:
        raise ValidationError("الفاتورة غير موجودة")
    items = conn.execute("""SELECT i.*, p.name FROM invoice_items i JOIN products p ON p.id=i.product_id
                            WHERE i.invoice_id=? ORDER BY i.id""", (invoice_id,)).fetchall()
    return {"invoice": inv, "items": items}


def list_invoices(conn, kind, limit=300):
    table = _TABLES[KINDS[kind]["party"]]
    return conn.execute(f"""SELECT i.*, p.name AS party_name, i.total_c - i.paid_c AS remaining_c
                            FROM invoices i JOIN {table} p ON p.id=i.party_id WHERE i.kind=? AND i.status='active'
                            ORDER BY i.invoice_date DESC, i.number DESC LIMIT ?""", (kind, limit)).fetchall()


def invoice_html(conn, invoice_id, shop_name=""):
    """نص HTML للفاتورة (للمعاينة والطباعة). الواجهة بتعرضه بس."""
    esc = html.escape
    data = get_invoice(conn, invoice_id)
    h, k = data["invoice"], KINDS[data["invoice"]["kind"]]
    party = conn.execute(f"SELECT name FROM {_TABLES[h['party_type']]} WHERE id=?", (h["party_id"],)).fetchone()[0]
    wh = conn.execute("SELECT name FROM warehouses WHERE id=?", (h["warehouse_id"],)).fetchone()[0]
    rows = "".join(f"<tr><td>{esc(i['name'])}</td><td align='center'>{fmt_qty(i['qty_m'])}</td>"
                   f"<td align='center'>{fmt_money(i['unit_price_c'])}</td>"
                   f"<td align='center'>{fmt_money(i['line_total_c'])}</td></tr>" for i in data["items"])
    cancelled = " (ملغية)" if h["status"] == "cancelled" else ""
    note = f"<p>ملاحظة: {esc(h['note'])}</p>" if h["note"] else ""
    shop = f"<h2 align='center'>{esc(shop_name)}</h2>" if shop_name else ""
    return f"""<html dir="rtl"><body dir="rtl" style="font-size:12pt">
{shop}<h2 align="center">{k['title']} رقم {h['number']}{cancelled}</h2>
<p>التاريخ: {h['invoice_date']}<br>{k['party_label']}: {esc(party)}<br>المخزن: {esc(wh)}</p>
<table dir="rtl" width="100%" border="1" cellspacing="0" cellpadding="6">
<tr bgcolor="#eeeeee"><th>الصنف</th><th>الكمية</th><th>السعر</th><th>الإجمالي</th></tr>{rows}</table>
<p>الإجمالي الفرعي: {fmt_money(h['subtotal_c'])}<br>الخصم: {fmt_money(h['discount_c'])}<br>
<b>الإجمالي: {fmt_money(h['total_c'])}</b><br>{k['cash_label']}: {fmt_money(h['paid_c'])}<br>
المتبقي: {fmt_money(h['total_c'] - h['paid_c'])}</p>{note}</body></html>"""
