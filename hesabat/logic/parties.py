"""العملاء والموردين (نفس المنطق). الرصيد = رصيد افتتاحي + مجموع party_ledger.
العميل: موجب = مستحق علينا له (مدين). المورد: موجب = مستحق له علينا."""
import sqlite3

from ..db.connection import tx
from .errors import ValidationError
from .money import parse_money
from .inventory import now_str

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


def statement(conn, kind, pid):
    """كشف حساب: صفوف (تاريخ، نوع، ملاحظة، مبلغ، رصيد تراكمي) والرصيد الحالي."""
    party = get(conn, kind, pid)
    running = party["opening_balance_c"]
    rows = [(party["created_at"], ENTRY_LABELS["opening"], "", running, running)]
    invoice_ids = [None]        # رقم الفاتورة (id) لكل صف في rows، أو None لو الصف مش مرتبط بفاتورة
    for e in conn.execute("SELECT * FROM party_ledger WHERE party_type=? AND party_id=? ORDER BY created_at,id",
                          (kind, pid)):
        running += e["amount_c"]
        rows.append((e["created_at"], ENTRY_LABELS[e["entry_type"]], e["note"], e["amount_c"], running))
        invoice_ids.append(e["ref_id"] if e["ref_type"] == "invoice" else None)
    return {"party": party, "rows": rows, "invoice_ids": invoice_ids, "balance_c": running}


def default_customer_id(conn):
    row = conn.execute("SELECT id FROM customers WHERE is_default=1 AND active=1").fetchone()
    return row[0] if row else None
