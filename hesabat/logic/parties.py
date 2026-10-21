"""العملاء والموردين (نفس المنطق). الرصيد = رصيد افتتاحي + مجموع party_ledger.
العميل: موجب = مستحق علينا له (مدين). المورد: موجب = مستحق له علينا."""
import sqlite3

from ..db.connection import tx
from .errors import ValidationError
from .money import parse_money
from .inventory import now_str
from .search import matches

TABLES = {"customer": "customers", "supplier": "suppliers"}
ENTRY_LABELS = {"opening": "رصيد افتتاحي", "invoice": "فاتورة", "payment": "دفعة / تحصيل",
                "return": "مرتجع", "adjust": "تسوية"}


def _table(kind):
    if kind not in TABLES:
        raise ValueError(kind)
    return TABLES[kind]


def _name(name):
    n = (name or "").strip()
    if not n:
        raise ValidationError("اكتب الاسم")
    return n


def list_parties(conn, kind):
    t = _table(kind)
    return conn.execute(f"""
        SELECT t.*, t.opening_balance_c + COALESCE(
            (SELECT SUM(amount_c) FROM party_ledger l WHERE l.party_type=? AND l.party_id=t.id),0) AS balance_c
        FROM {t} t WHERE t.active=1 ORDER BY t.name""", (kind,)).fetchall()


def search(rows, query):
    """فلترة قائمة العملاء/الموردين بالاسم أو التليفون (بحث عربي: بيتجاهل التشكيل وأ/ا وة/ه والأرقام العربية)."""
    return [r for r in rows if matches(query, f"{r['name']} {r['phone']}")]


def balance(conn, kind, pid):
    """الرصيد الحالي للطرف (رصيد افتتاحي + كل القيود). الموجب = مستحق على العميل / للمورد."""
    t = _table(kind)
    return conn.execute(f"""
        SELECT t.opening_balance_c + COALESCE(
            (SELECT SUM(amount_c) FROM party_ledger l WHERE l.party_type=? AND l.party_id=t.id),0)
        FROM {t} t WHERE t.id=?""", (kind, pid)).fetchone()[0]


def get(conn, kind, pid):
    row = conn.execute(f"SELECT * FROM {_table(kind)} WHERE id=? AND active=1", (pid,)).fetchone()
    if not row:
        raise ValidationError("غير موجود")
    return row


def create(conn, kind, name, phone="", address="", notes="", opening_balance="0"):
    ob = parse_money(opening_balance, "الرصيد الافتتاحي", allow_negative=True, allow_empty=True)
    with tx(conn):
        try:
            return conn.execute(
                f"INSERT INTO {_table(kind)}(name,phone,address,notes,opening_balance_c,created_at) VALUES(?,?,?,?,?,?)",
                (_name(name), phone.strip(), address.strip(), notes.strip(), ob, now_str())).lastrowid
        except sqlite3.IntegrityError:
            raise ValidationError("الاسم موجود بالفعل (ممكن يكون محذوف سابقاً)")


def update(conn, kind, pid, name, phone="", address="", notes="", opening_balance="0"):
    ob = parse_money(opening_balance, "الرصيد الافتتاحي", allow_negative=True, allow_empty=True)
    with tx(conn):
        get(conn, kind, pid)
        try:
            conn.execute(f"UPDATE {_table(kind)} SET name=?,phone=?,address=?,notes=?,opening_balance_c=? WHERE id=?",
                         (_name(name), phone.strip(), address.strip(), notes.strip(), ob, pid))
        except sqlite3.IntegrityError:
            raise ValidationError("الاسم مستخدم لحد تاني")


def deactivate(conn, kind, pid):
    with tx(conn):
        row = get(conn, kind, pid)
        if kind == "customer" and row["is_default"]:
            raise ValidationError("العميل النقدي الافتراضي لا يمكن حذفه")
        conn.execute(f"UPDATE {_table(kind)} SET active=0 WHERE id=?", (pid,))


def add_ledger_entry(conn, kind, pid, entry_type, amount_c, ref_type=None, ref_id=None, note="", created_at=None):
    """بتستخدمها الفواتير والمدفوعات في المراحل الجاية (جوه transaction الفاتورة)."""
    return conn.execute(
        "INSERT INTO party_ledger(party_type,party_id,entry_type,amount_c,ref_type,ref_id,note,created_at) "
        "VALUES(?,?,?,?,?,?,?,?)", (kind, pid, entry_type, amount_c, ref_type, ref_id, note, created_at or now_str())).lastrowid


def cancelled_pairs(conn, kind, pid):
    """السطور الملغية في كشف الحساب: {id القيد: id القيد المقابل}. السطر الملغي دايماً ليه مقابل بيعكسه
    (سند اتلغى وفيه سطر «إلغاء سند»، أو فاتورة اتعدّلت وفيها سطر «إلغاء/تعديل») ومجموعهم صفر."""
    ents = conn.execute("SELECT * FROM party_ledger WHERE party_type=? AND party_id=? ORDER BY created_at,id",
                        (kind, pid)).fetchall()
    pairs = {}
    by_voucher = {}
    for e in ents:
        if e["ref_type"] in ("treasury", "treasury_void"):
            by_voucher.setdefault(e["ref_id"], []).append(e)
    for group in by_voucher.values():
        orig = [e for e in group if e["ref_type"] == "treasury"]
        void = [e for e in group if e["ref_type"] == "treasury_void"]
        if len(orig) == 1 and len(void) == 1 and orig[0]["amount_c"] + void[0]["amount_c"] == 0:
            pairs[orig[0]["id"], void[0]["id"]] = None
    open_inv = {}                       # فاتورة -> قيودها الأصلية اللي لسه مالهاش مقابل
    for e in ents:
        if e["ref_type"] != "invoice":
            continue
        if e["entry_type"] == "adjust":
            for o in reversed(open_inv.get(e["ref_id"], [])):
                if o["amount_c"] == -e["amount_c"]:
                    open_inv[e["ref_id"]].remove(o)
                    pairs[o["id"], e["id"]] = None
                    break
        else:
            open_inv.setdefault(e["ref_id"], []).append(e)
    out = {}
    for x, y in pairs:
        out[x], out[y] = y, x
    return out


def remove_cancelled(conn, kind, pid, ledger_id):
    """بيمسح سطر ملغي ومقابله من كشف الحساب. الرصيد مبيتغيرش (مجموعهم صفر)."""
    with tx(conn):
        pairs = cancelled_pairs(conn, kind, pid)
        if ledger_id not in pairs:
            raise ValidationError("السطر ده مش ملغي، أو اتمسح قبل كده")
        before = balance(conn, kind, pid)
        conn.execute("DELETE FROM party_ledger WHERE id IN (?,?)", (ledger_id, pairs[ledger_id]))
        if balance(conn, kind, pid) != before:
            raise ValidationError("مقدرتش أمسح السطر لأن ده هيغيّر الرصيد. متمسحش.")


def statement(conn, kind, pid):
    """كشف حساب: صفوف (تاريخ، نوع، ملاحظة، مبلغ، رصيد تراكمي) والرصيد الحالي.
    ledger_ids: id قيد كل صف (None للافتتاحي) | removable: هل الصف ملغي ويينفع يتمسح."""
    party = get(conn, kind, pid)
    running = party["opening_balance_c"]
    rows = [(party["created_at"], ENTRY_LABELS["opening"], "", running, running)]
    invoice_ids = [None]        # رقم الفاتورة (id) لكل صف في rows، أو None لو الصف مش مرتبط بفاتورة
    ledger_ids, cancelled = [None], cancelled_pairs(conn, kind, pid)
    for e in conn.execute("SELECT * FROM party_ledger WHERE party_type=? AND party_id=? ORDER BY created_at,id",
                          (kind, pid)):
        running += e["amount_c"]
        rows.append((e["created_at"], ENTRY_LABELS[e["entry_type"]], e["note"], e["amount_c"], running))
        invoice_ids.append(e["ref_id"] if e["ref_type"] == "invoice" else None)
        ledger_ids.append(e["id"])
    return {"party": party, "rows": rows, "invoice_ids": invoice_ids, "balance_c": running,
            "ledger_ids": ledger_ids, "removable": [i in cancelled for i in ledger_ids]}


def default_customer_id(conn):
    row = conn.execute("SELECT id FROM customers WHERE is_default=1 AND active=1").fetchone()
    return row[0] if row else None
