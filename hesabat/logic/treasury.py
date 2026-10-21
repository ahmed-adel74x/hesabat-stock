"""
الخزينة. الرصيد = الرصيد الافتتاحي + مجموع القبض - مجموع الصرف (للسندات غير الملغية).

الربط مع العملاء/الموردين: أي سند مرتبط بطرف بيتسجل أوتوماتيك في دفتر حسابه (party_ledger) في نفس الـ transaction.
فواتير الشراء والبيع (المرحلة 3 و4) هتنادي add_entry(..., ref_type='invoice', ref_id=رقم الفاتورة) فتتسجل في الخزينة
وحساب الطرف مع بعض، من غير ما الفاتورة تسجّل دفعة الطرف بنفسها.
"""
from datetime import datetime

from ..db.connection import tx
from . import parties
from .errors import ValidationError
from .money import _AR_DIGITS, parse_money

KIND_LABELS = {"receipt": "سند قبض", "payment": "سند صرف"}


def today():
    return datetime.now().strftime("%Y-%m-%d")


def month_start():
    return datetime.now().strftime("%Y-%m-01")


def _parse_date(text, field="التاريخ"):
    s = str(text or "").strip().translate(_AR_DIGITS).replace("/", "-")
    try:
        return datetime.strptime(s, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        raise ValidationError(f"{field}: اكتبه بالشكل 2026-10-08")


def _past_date(text, field="التاريخ"):
    d = _parse_date(text, field)
    if d > today():
        raise ValidationError(f"{field}: التاريخ في المستقبل")
    return d


# ---------------------------------------------------------------- إعدادات وأرصدة
def get_opening(conn):
    return int(conn.execute("SELECT value FROM app_settings WHERE key='treasury_opening_c'").fetchone()[0])


def last_closing_date(conn):
    return conn.execute("SELECT MAX(close_date) FROM treasury_closings").fetchone()[0]


def set_opening(conn, amount):
    c = parse_money(amount, "الرصيد الافتتاحي", allow_empty=True)
    with tx(conn):
        if last_closing_date(conn):
            raise ValidationError("مينفعش تغيّر الرصيد الافتتاحي بعد أول تقفيل يومي")
        conn.execute("UPDATE app_settings SET value=? WHERE key='treasury_opening_c'", (str(c),))


def _net(conn, where="", args=()):
    return conn.execute("SELECT COALESCE(SUM(CASE kind WHEN 'receipt' THEN amount_c ELSE -amount_c END),0) "
                        f"FROM treasury_entries WHERE voided=0 {where}", args).fetchone()[0]


def balance(conn, upto=None):
    if upto:
        return get_opening(conn) + _net(conn, "AND entry_date <= ?", (upto,))
    return get_opening(conn) + _net(conn)


def summary(conn):
    t = today()
    row = conn.execute("SELECT COALESCE(SUM(CASE kind WHEN 'receipt' THEN amount_c END),0), "
                       "COALESCE(SUM(CASE kind WHEN 'payment' THEN amount_c END),0) "
                       "FROM treasury_entries WHERE voided=0 AND entry_date=?", (t,)).fetchone()
    return {"balance_c": balance(conn), "opening_c": get_opening(conn), "today_in": row[0],
            "today_out": row[1], "last_close": last_closing_date(conn)}


# ---------------------------------------------------------------- السندات
def _check_open(conn, d):
    last = last_closing_date(conn)
    if last and d <= last:
        raise ValidationError(f"الفترة دي مقفولة (آخر تقفيل {last}). مينفعش تضيف أو تلغي سندات بتاريخ {last} أو قبله")


def _insert(conn, kind, amount_c, party_type, party_id, category, note, entry_date, ref_type, ref_id):
    return conn.execute(
        "INSERT INTO treasury_entries(kind,amount_c,party_type,party_id,category,ref_type,ref_id,note,entry_date,created_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (kind, amount_c, party_type, party_id, category, ref_type, ref_id, note, entry_date,
         datetime.now().strftime("%Y-%m-%d %H:%M:%S"))).lastrowid


def _sign(kind, party_type):
    """أثر السند على رصيد الطرف: قبض من عميل / صرف لمورد بينقص الرصيد المستحق، والعكس بيزوّده."""
    return -1 if (kind == "receipt") == (party_type == "customer") else 1


def add_entry(conn, kind, amount_c, party_type=None, party_id=None, category="", note="",
              entry_date=None, ref_type="voucher", ref_id=None):
    """بتسجّل سند قبض/صرف (المبلغ بالقروش). بتتنادي جوه transaction الفاتورة أو لوحدها."""
    if kind not in KIND_LABELS:
        raise ValueError(kind)
    if not isinstance(amount_c, int) or amount_c <= 0:
        raise ValidationError("المبلغ: لازم يكون أكبر من صفر")
    d = _past_date(entry_date) if entry_date else today()
    category, note = (category or "").strip(), (note or "").strip()
    if party_type is None and not category:
        raise ValidationError("اكتب بيان السند (مثال: إيجار، كهرباء، إيراد آخر)")
    with tx(conn):
        _check_open(conn, d)
        if party_type is not None:
            parties.get(conn, party_type, party_id)  # يتأكد إن الطرف موجود
        eid = _insert(conn, kind, amount_c, party_type, party_id, category, note, d, ref_type, ref_id)
        if party_type is not None:
            parties.add_ledger_entry(conn, party_type, party_id, "payment", _sign(kind, party_type) * amount_c,
                                     "treasury", eid, note or KIND_LABELS[kind],
                                     f"{d} {datetime.now():%H:%M:%S}")
        return eid


def add_voucher(conn, kind, amount, party_type=None, party_id=None, category="", note="", entry_date=None):
    """نسخة الواجهة: المبلغ كنص بالجنيه."""
    return add_entry(conn, kind, parse_money(amount, "المبلغ"), party_type, party_id, category, note, entry_date)


def _void(conn, e):
    """بيلغي السند ويعكس أثره على حساب الطرف. بيرفض لو الفترة مقفولة."""
    _check_open(conn, e["entry_date"])
    conn.execute("UPDATE treasury_entries SET voided=1 WHERE id=?", (e["id"],))
    if e["party_type"]:
        parties.add_ledger_entry(conn, e["party_type"], e["party_id"], "adjust",
                                 -_sign(e["kind"], e["party_type"]) * e["amount_c"],
                                 "treasury_void", e["id"], f"إلغاء سند رقم {e['id']}")


def void_linked(conn, ref_type, ref_id):
    """بتلغي سندات مرتبطة بعملية تانية (مثلاً دفعات فاتورة بتتلغي أو بتتعدّل)."""
    with tx(conn):
        for e in conn.execute("SELECT * FROM treasury_entries WHERE ref_type=? AND ref_id=? AND voided=0",
                              (ref_type, ref_id)).fetchall():
            _void(conn, e)


def void_entry(conn, entry_id):
    """بيلغي السند ويمسحه خالص: بيتشال من الخزينة ومن كشف حساب الطرف (مبيفضلش له أثر ولا سطر "ملغي")."""
    with tx(conn):
        e = conn.execute("SELECT * FROM treasury_entries WHERE id=?", (entry_id,)).fetchone()
        if not e or e["voided"]:
            raise ValidationError("السند غير موجود")
        if e["ref_type"] == "invoice":
            raise ValidationError("السند ده مرتبط بفاتورة. عدّل الفاتورة نفسها بدل ما تلغيه.")
        if e["ref_type"] == "closing":
            raise ValidationError("ده سند تسوية تقفيل. بيتلغي بإلغاء التقفيل.")
        _check_open(conn, e["entry_date"])
        # مسح قيد السند من حساب الطرف = نفس أثر العكس، من غير ما يفضل سطر إلغاء في الكشف
        conn.execute("DELETE FROM party_ledger WHERE ref_type IN ('treasury','treasury_void') AND ref_id=?", (entry_id,))
        conn.execute("DELETE FROM treasury_entries WHERE id=?", (entry_id,))


def recent_entries(conn, limit=100):
    return conn.execute("""
        SELECT e.id, e.entry_date, e.kind, e.amount_c, e.voided, e.ref_type, e.note,
               COALESCE(c.name, s.name, e.category) AS what
        FROM treasury_entries e
        LEFT JOIN customers c ON e.party_type='customer' AND c.id=e.party_id
        LEFT JOIN suppliers s ON e.party_type='supplier' AND s.id=e.party_id
        WHERE e.voided=0
        ORDER BY e.entry_date DESC, e.id DESC LIMIT ?""", (limit,)).fetchall()


def statement(conn, date_from=None, date_to=None):
    """كشف حركة الخزينة بين تاريخين مع رصيد تراكمي."""
    dfrom = _parse_date(date_from, "من تاريخ") if date_from else None
    dto = _parse_date(date_to, "إلى تاريخ") if date_to else None
    if dfrom and dto and dfrom > dto:
        raise ValidationError("تاريخ البداية بعد تاريخ النهاية")
    opening = get_opening(conn) + (_net(conn, "AND entry_date < ?", (dfrom,)) if dfrom else 0)
    where, args = "WHERE e.voided=0", []
    if dfrom:
        where += " AND e.entry_date >= ?"; args.append(dfrom)
    if dto:
        where += " AND e.entry_date <= ?"; args.append(dto)
    rows, running, tin, tout = [], opening, 0, 0
    for e in conn.execute(f"""
            SELECT e.id, e.entry_date, e.kind, e.amount_c, e.note,
                   COALESCE(c.name, s.name, e.category) AS what
            FROM treasury_entries e
            LEFT JOIN customers c ON e.party_type='customer' AND c.id=e.party_id
            LEFT JOIN suppliers s ON e.party_type='supplier' AND s.id=e.party_id
            {where} ORDER BY e.entry_date, e.id""", args):
        i, o = (e["amount_c"], 0) if e["kind"] == "receipt" else (0, e["amount_c"])
        running += i - o
        tin, tout = tin + i, tout + o
        text = e["what"] + (f" - {e['note']}" if e["note"] else "")
        rows.append({"id": e["id"], "date": e["entry_date"], "label": KIND_LABELS[e["kind"]], "text": text,
                     "in_c": i, "out_c": o, "running_c": running})
    return {"opening_c": opening, "rows": rows, "total_in": tin, "total_out": tout, "closing_c": running}


# ---------------------------------------------------------------- التقفيل اليومي
def close_day(conn, close_date=None, counted="", note=""):
    """تقفيل: بيجمّد كل السندات لحد التاريخ ده. لو كتبت النقدية الفعلية واختلفت عن الدفتري
    بيتسجل سند تسوية (عجز/زيادة) أوتوماتيك عشان الرصيد الدفتري يساوي الفعلي."""
    d = _past_date(close_date) if close_date else today()
    counted_c = None if str(counted or "").strip() == "" else parse_money(counted, "النقدية الفعلية")
    with tx(conn):
        last = last_closing_date(conn)
        if last and d <= last:
            raise ValidationError(f"اليوم ده اتقفل بالفعل (آخر تقفيل {last})")
        opening = balance(conn, last) if last else get_opening(conn)
        book = balance(conn, d)
        diff = 0 if counted_c is None else counted_c - book
        cid = conn.execute("INSERT INTO treasury_closings(close_date,opening_c,receipts_c,payments_c,closing_c,"
                           "counted_c,diff_c,note,created_at) VALUES(?,?,0,0,0,?,?,?,?)",
                           (d, opening, counted_c, diff, (note or "").strip(),
                            datetime.now().strftime("%Y-%m-%d %H:%M:%S"))).lastrowid
        if diff:
            _insert(conn, "receipt" if diff > 0 else "payment", abs(diff), None, None,
                    "زيادة جرد الخزينة" if diff > 0 else "عجز جرد الخزينة", "تسوية تقفيل", d, "closing", cid)
        lo, args = ("AND entry_date > ?", (last, d)) if last else ("", (d,))
        r = conn.execute("SELECT COALESCE(SUM(CASE kind WHEN 'receipt' THEN amount_c END),0), "
                         "COALESCE(SUM(CASE kind WHEN 'payment' THEN amount_c END),0) "
                         f"FROM treasury_entries WHERE voided=0 {lo} AND entry_date <= ?", args).fetchone()
        conn.execute("UPDATE treasury_closings SET receipts_c=?, payments_c=?, closing_c=? WHERE id=?",
                     (r[0], r[1], opening + r[0] - r[1], cid))
        return cid


def reopen_last_closing(conn):
    with tx(conn):
        row = conn.execute("SELECT * FROM treasury_closings ORDER BY close_date DESC LIMIT 1").fetchone()
        if not row:
            raise ValidationError("مفيش تقفيل يتلغي")
        conn.execute("UPDATE treasury_entries SET voided=1 WHERE ref_type='closing' AND ref_id=?", (row["id"],))
        conn.execute("DELETE FROM treasury_closings WHERE id=?", (row["id"],))
        return row["close_date"]


def list_closings(conn):
    return conn.execute("SELECT * FROM treasury_closings ORDER BY close_date DESC").fetchall()


past_date = _past_date
parse_date = _parse_date
