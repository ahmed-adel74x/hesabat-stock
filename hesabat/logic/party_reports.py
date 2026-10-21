"""تقارير الطباعة الخاصة بعميل/مورد واحد:
  statement_html : كل التعاملات (كشف الحساب كامل + تفاصيل أصناف كل فاتورة).
  dues_html      : المتبقي: كل فاتورة (الإجمالي / المدفوع / المتبقي) والدفعات المستقلة وإجمالي اللي عليه يدفعه.
الأرقام بتتحسب من نفس جداول الحساب (فواتير + دفتر الطرف)، والإجمالي النهائي = رصيد الطرف الحالي بالظبط."""
import html
from datetime import datetime

from . import parties
from .invoices import KINDS
from .money import fmt_money, fmt_qty

_LRM = "‎"          # بيمنع علامة السالب من إنها تتقلب في الفقرات العربية (-100 مش 100-)


def _m(c):
    return _LRM + fmt_money(c)


def _head(party, kind, title):
    esc = html.escape
    lines = [f"{'العميل' if kind == 'customer' else 'المورد'}: <b>{esc(party['name'])}</b>"]
    if party["phone"]:
        lines.append(f"التليفون: {esc(party['phone'])}")
    if party["address"]:
        lines.append(f"العنوان: {esc(party['address'])}")
    lines.append(f"تاريخ الطباعة: {datetime.now():%Y-%m-%d %H:%M}")
    return f"<h2 align='center'>{title}</h2><p>{'<br>'.join(lines)}</p>"


def _owed_text(kind, bal):
    cust = kind == "customer"
    if bal > 0:
        return ("إجمالي المتبقي على العميل" if cust else "إجمالي المتبقي للمورد علينا"), bal
    if bal < 0:
        return ("رصيد دائن للعميل - له عندنا" if cust else "رصيد للمورد عليه - دفعنا له زيادة"), -bal
    return "الحساب مسدّد بالكامل - المتبقي", 0


def _table(headers, rows, widths=None):
    th = "".join(f"<th>{h}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td align='center'>{c}</td>" for c in r) + "</tr>" for r in rows)
    return (f"<table dir='rtl' width='100%' border='1' cellspacing='0' cellpadding='5'>"
            f"<tr bgcolor='#eeeeee'>{th}</tr>{body}</table>")


def _items_text(conn, invoice_id):
    """أصناف الفاتورة في سطر واحد: سكر × 2 ، زيت × 1.5"""
    rows = conn.execute("""SELECT p.name, i.qty_m FROM invoice_items i JOIN products p ON p.id=i.product_id
                           WHERE i.invoice_id=? ORDER BY i.id""", (invoice_id,)).fetchall()
    return html.escape(" ، ".join(f"{r['name']} × {fmt_qty(r['qty_m'])}" for r in rows))


def _party_invoices(conn, kind, pid):
    return conn.execute("SELECT * FROM invoices WHERE party_type=? AND party_id=? AND status='active' "
                        "ORDER BY invoice_date, id", (kind, pid)).fetchall()


def statement_html(conn, kind, pid):
    """كل تعاملات الطرف: الحركات بالترتيب مع الرصيد التراكمي، وبعدها تفاصيل أصناف كل فاتورة."""
    esc = html.escape
    data = parties.statement(conn, kind, pid)
    party = data["party"]
    rows = []
    for r, iid in zip(data["rows"], data["invoice_ids"]):
        items = _items_text(conn, iid) if iid is not None and r[1] in ("فاتورة", "مرتجع") else ""
        rows.append((r[0][:16], esc(r[1]), esc(r[2] or ""), items, _m(r[3]), _m(r[4])))
    out = [f"<html dir='rtl'><body dir='rtl' style='font-size:10pt'>",
           _head(party, kind, "كشف حساب تفصيلي - كل التعاملات"),
           _table(["التاريخ", "البيان", "ملاحظة", "الأصناف", "المبلغ", "الرصيد"], rows)]
    invs = _party_invoices(conn, kind, pid)
    if invs:
        out.append("<h3>تفاصيل الفواتير</h3>")
        for inv in invs:
            k = KINDS[inv["kind"]]
            items = conn.execute("""SELECT i.*, p.name FROM invoice_items i JOIN products p ON p.id=i.product_id
                                    WHERE i.invoice_id=? ORDER BY i.id""", (inv["id"],)).fetchall()
            out.append(f"<p><b>{k['title']} رقم {inv['number']}</b> - {inv['invoice_date']} &nbsp;|&nbsp; "
                       f"الإجمالي: {_m(inv['total_c'])} &nbsp;|&nbsp; {k['cash_label']}: {_m(inv['paid_c'])} "
                       f"&nbsp;|&nbsp; المتبقي: {_m(inv['total_c'] - inv['paid_c'])}"
                       + (f"<br>ملاحظة: {esc(inv['note'])}" if inv["note"] else "") + "</p>")
            out.append(_table(["الصنف", "الكمية", "السعر", "الإجمالي"],
                              [(esc(i["name"]), fmt_qty(i["qty_m"]), _m(i["unit_price_c"]), _m(i["line_total_c"]))
                               for i in items]))
            if inv["discount_c"]:
                out.append(f"<p>الخصم: {_m(inv['discount_c'])}</p>")
    label, amount = _owed_text(kind, data["balance_c"])
    out.append(f"<br><table dir='rtl' width='100%' border='1' cellspacing='0' cellpadding='8'>"
               f"<tr bgcolor='#f3f4f6'><td><b>{label}</b></td><td align='center'><b style='font-size:14pt'>"
               f"{_m(amount)}</b></td></tr></table></body></html>")
    return "".join(out)


def dues_data(conn, kind, pid):
    """بيانات تقرير المتبقي: (الطرف، رصيد افتتاحي، صفوف الفواتير، الدفعات المستقلة، تسويات أخرى، الرصيد الحالي).
    أثر كل فاتورة على الرصيد = إشارتها × (الإجمالي - المدفوع). والباقي (الافتتاحي + الدفعات المستقلة) من الدفتر."""
    party = parties.get(conn, kind, pid)
    inv_rows, inv_effect = [], 0
    for inv in _party_invoices(conn, kind, pid):
        k = KINDS[inv["kind"]]
        effect = k["ledger_sign"] * (inv["total_c"] - inv["paid_c"])
        inv_effect += effect
        inv_rows.append({"title": k["title"], "number": inv["number"], "date": inv["invoice_date"],
                         "total_c": inv["total_c"], "paid_c": inv["paid_c"], "effect_c": effect,
                         "items": _items_text(conn, inv["id"]),
                         "is_return": k["ledger_sign"] < 0})
    pay_rows = conn.execute("""SELECT l.created_at, l.amount_c, l.note FROM party_ledger l
                               JOIN treasury_entries t ON l.ref_type='treasury' AND l.ref_id=t.id
                               WHERE l.party_type=? AND l.party_id=? AND t.voided=0 AND t.ref_type<>'invoice'
                               ORDER BY l.created_at, l.id""", (kind, pid)).fetchall()
    pay_total = sum(r["amount_c"] for r in pay_rows)
    bal = parties.balance(conn, kind, pid)
    other = bal - party["opening_balance_c"] - inv_effect - pay_total    # المفروض صفر؛ بنعرضه لو حصل فرق عشان الإجمالي يتطابق
    return party, party["opening_balance_c"], inv_rows, pay_rows, other, bal


def dues_html(conn, kind, pid):
    esc = html.escape
    party, opening, inv_rows, pay_rows, other, bal = dues_data(conn, kind, pid)
    out = ["<html dir='rtl'><body dir='rtl' style='font-size:10pt'>",
           _head(party, kind, "كشف المتبقي - الفواتير والمدفوع والباقي")]
    if opening:
        out.append(f"<p>رصيد افتتاحي قبل البرنامج: <b>{_m(opening)}</b></p>")
    if inv_rows:
        rows = []
        for r in inv_rows:
            rem = _m(r["effect_c"])
            if r["effect_c"] and not r["is_return"]:
                rem = f"<b>{rem}</b>"
            rows.append((f"{r['title']} رقم {r['number']}", r["date"], r["items"], _m(r["total_c"]), _m(r["paid_c"]), rem))
        out.append(_table(["الفاتورة", "التاريخ", "الأصناف", "الإجمالي", "المدفوع", "المتبقي"], rows))
        out.append("<p style='font-size:9pt'>المرتجعات بتظهر بالسالب لأنها بتخصم من المتبقي.</p>")
    else:
        out.append("<p>مفيش فواتير.</p>")
    if pay_rows:
        out.append("<h3>دفعات / تحصيلات مستقلة - مش على فاتورة معينة</h3>")
        out.append(_table(["التاريخ", "البيان", "المبلغ"],
                          [(r["created_at"][:16], esc(r["note"] or ""), _m(r["amount_c"])) for r in pay_rows]))
    if other:
        out.append(f"<p>تسويات أخرى: <b>{_m(other)}</b></p>")
    label, amount = _owed_text(kind, bal)
    out.append(f"<br><table dir='rtl' width='100%' border='1' cellspacing='0' cellpadding='8'>"
               f"<tr bgcolor='#f3f4f6'><td><b>{label}</b></td><td align='center'><b style='font-size:15pt'>"
               f"{_m(amount)}</b></td></tr></table></body></html>")
    return "".join(out)
