"""
ترحيل قاعدة البيانات القديمة (products.qty + moves) للهيكل الجديد (stock_movements).

الأمان:
  1) نسخة احتياطية كاملة قبل أي تعديل (فولدر backups جنب stock.db).
  2) الترحيل كله جوه transaction واحدة، وبعده بيتعمل تقرير مطابقة (قبل/بعد).
     لو أي رقم مش متطابق: rollback كامل وقاعدة البيانات ترجع زي ما كانت، وبيرمي MigrationError.
  3) الجداول القديمة بتفضل جوه الملف باسم legacy_products و legacy_moves للرجوع إليها.
"""
import os
from datetime import datetime
from decimal import Decimal

from .connection import backup_db, tx
from .schema import SCHEMA_VERSION, UPGRADE_STEPS, V1_STATEMENTS
from ..logic.money import to_cents, to_milli

OPENING_DATE = "2000-01-01 00:00:00"


class MigrationError(Exception):
    def __init__(self, message, report=None):
        super().__init__(message)
        self.report = report


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _seed(conn, now):
    conn.execute("INSERT INTO warehouses(id,name,created_at) VALUES(1,'المخزن الرئيسي',?)", (now,))
    conn.execute("INSERT INTO customers(id,name,is_default,created_at) VALUES(1,'عميل نقدي',1,?)", (now,))


def _create_schema(conn):
    for st in V1_STATEMENTS:
        conn.execute(st)


def _create_steps(conn, upto=SCHEMA_VERSION, start=2):
    for v in range(start, upto + 1):
        for st in UPGRADE_STEPS[v]:
            conn.execute(st)


def init_db(conn, db_path):
    """بتجهّز/بترقّي قاعدة البيانات لآخر نسخة (كل خطوة بنسخة احتياطية وtransaction).
    بترجع تقرير الترحيل من القاعدة القديمة لو حصل، وإلا None."""
    ver = conn.execute("PRAGMA user_version").fetchone()[0]
    if ver >= SCHEMA_VERSION:
        return None
    report = None
    if ver == 0:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        if not tables:  # قاعدة جديدة
            with tx(conn):
                _create_schema(conn)
                _create_steps(conn)
                _seed(conn, _now())
                conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            return None
        cols = [r[1] for r in conn.execute("PRAGMA table_info(products)")] if "products" in tables else []
        if "buy" in cols and "moves" in tables:
            backup = backup_db(conn, db_path, "before_v1")
            report = _migrate_legacy(conn, backup)  # بينتهي عند النسخة 1
            txt = os.path.join(os.path.dirname(backup), os.path.basename(backup).replace(".db", "_report.txt"))
            with open(txt, "w", encoding="utf-8") as f:
                f.write(report["text"])
            report["report_file"] = txt
        else:
            raise MigrationError("هيكل قاعدة البيانات غير معروف، مش هعدّل فيه.")
    _upgrade(conn, db_path)
    return report


def _upgrade(conn, db_path):
    """ترقية خطوة خطوة لحد آخر نسخة. كل خطوة: نسخة احتياطية + transaction. بياناتك الحالية مبتتلمسش."""
    while True:
        ver = conn.execute("PRAGMA user_version").fetchone()[0]
        if ver >= SCHEMA_VERSION:
            return
        nxt = ver + 1
        backup_db(conn, db_path, f"before_v{nxt}")
        with tx(conn):
            _create_steps(conn, upto=nxt, start=nxt)
            conn.execute(f"PRAGMA user_version = {nxt}")


# ---------------------------------------------------------------- قبل
def snapshot_legacy(conn):
    P = conn.execute("SELECT id,buy,sell,qty FROM products").fetchall()
    M = conn.execute("SELECT pid,kind,qty,price,cost FROM moves").fetchall()
    D = Decimal
    s = {
        "products": len(P),
        "qty_m": sum(to_milli(r["qty"] or 0) for r in P),
        "stock_cost_value": sum(D(str(r["qty"] or 0)) * D(str(r["buy"] or 0)) for r in P),
        "stock_sell_value": sum(D(str(r["qty"] or 0)) * D(str(r["sell"] or 0)) for r in P),
        "moves": len(M),
        "sales_total": sum(D(str(r["qty"])) * D(str(r["price"])) for r in M if r["kind"] == "sale"),
        "purchases_total": sum(D(str(r["qty"])) * D(str(r["price"])) for r in M if r["kind"] == "purchase"),
        "profit": sum(D(str(r["qty"])) * (D(str(r["price"])) - D(str(r["cost"] or 0)))
                      for r in M if r["kind"] == "sale"),
        "per_product_qty_m": {r["id"]: to_milli(r["qty"] or 0) for r in P},
        "orphan_moves": 0,
        "negative_products": sum(1 for r in P if (r["qty"] or 0) < 0),
    }
    ids = {r["id"] for r in P}
    s["orphan_moves"] = sum(1 for r in M if r["pid"] not in ids)
    s["_rows"] = len(P) + len(M)
    return s


# ---------------------------------------------------------------- بعد
def snapshot_new(conn):
    D = Decimal
    rows = conn.execute("""
        SELECT p.id, p.buy_price_c, p.sell_price_c, COALESCE(SUM(m.qty_m),0) AS q
        FROM products p LEFT JOIN stock_movements m ON m.product_id = p.id
        WHERE p.active = 1 GROUP BY p.id""").fetchall()
    mv = conn.execute("SELECT kind,qty_m,unit_price_c,unit_cost_c FROM stock_movements "
                      "WHERE kind IN ('purchase','sale')").fetchall()
    k = D(100000)  # (ألف) × (قروش 100)
    return {
        "products": len(rows),
        "qty_m": sum(r["q"] for r in rows),
        "stock_cost_value": D(sum(r["q"] * r["buy_price_c"] for r in rows)) / k,
        "stock_sell_value": D(sum(r["q"] * r["sell_price_c"] for r in rows)) / k,
        "moves": len(mv),
        "sales_total": D(sum(-r["qty_m"] * r["unit_price_c"] for r in mv if r["kind"] == "sale")) / k,
        "purchases_total": D(sum(r["qty_m"] * r["unit_price_c"] for r in mv if r["kind"] == "purchase")) / k,
        "profit": D(sum(-r["qty_m"] * (r["unit_price_c"] - r["unit_cost_c"]) for r in mv if r["kind"] == "sale")) / k,
        "per_product_qty_m": {r["id"]: r["q"] for r in rows},
    }


LABELS = [
    ("products", "عدد الأصناف"),
    ("qty_m", "مجموع الأرصدة (بالألف)"),
    ("stock_cost_value", "قيمة المخزون بسعر الشراء"),
    ("stock_sell_value", "قيمة المخزون بسعر البيع"),
    ("moves", "عدد حركات البيع/الشراء"),
    ("sales_total", "إجمالي المبيعات"),
    ("purchases_total", "إجمالي المشتريات"),
    ("profit", "إجمالي الربح"),
]


def build_report(before, after, backup):
    tol = Decimal("0.005") * max(1, before["_rows"])  # نص قرش لكل صف كحد أقصى للتقريب
    lines, ok = [], True
    for key, label in LABELS:
        b, a = Decimal(before[key]), Decimal(after[key])
        exact = key in ("products", "qty_m", "moves")
        good = (a == b) if exact else (abs(a - b) <= tol)
        ok &= good
        lines.append(f"{'✔' if good else '✘'} {label}: قبل={b:,.2f}  بعد={a:,.2f}  الفرق={a - b:,.2f}")
    bad = [pid for pid, q in before["per_product_qty_m"].items() if after["per_product_qty_m"].get(pid) != q]
    ok &= not bad
    lines.append(f"{'✔' if not bad else '✘'} رصيد كل صنف على حدة: " +
                 ("متطابق" if not bad else f"فروق في الأصناف رقم {bad}"))
    warnings = []
    if before["orphan_moves"]:
        warnings.append(f"{before['orphan_moves']} حركة لأصناف محذوفة سابقاً اتنقلت لأصناف أرشيف (غير نشطة).")
    if before["negative_products"]:
        warnings.append(f"{before['negative_products']} صنف رصيده سالب في البيانات القديمة (اتنقل زي ما هو).")
    head = ["تقرير ترحيل قاعدة البيانات", "=" * 34, f"النسخة الاحتياطية: {backup}", ""]
    text = "\n".join(head + lines + ([""] + ["تنبيه: " + w for w in warnings] if warnings else []) +
                     ["", "النتيجة: " + ("متطابق ✔" if ok else "غير متطابق ✘ (تم التراجع)")])
    return {"ok": ok, "text": text, "backup": backup, "warnings": warnings}


# ---------------------------------------------------------------- الترحيل
def _migrate_legacy(conn, backup):
    before = snapshot_legacy(conn)
    now = _now()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("ALTER TABLE products RENAME TO legacy_products")
        conn.execute("ALTER TABLE moves RENAME TO legacy_moves")
        _create_schema(conn)
        _seed(conn, now)

        legacy = conn.execute("SELECT id,name,buy,sell,qty,min_qty FROM legacy_products ORDER BY id").fetchall()
        known = {}
        for r in legacy:
            buy_c = to_cents(r["buy"] or 0)
            conn.execute("INSERT INTO products(id,name,sell_price_c,buy_price_c,avg_cost_c,min_qty_m,created_at) "
                         "VALUES(?,?,?,?,?,?,?)",
                         (r["id"], r["name"], to_cents(r["sell"] or 0), buy_c, buy_c,
                          max(0, to_milli(r["min_qty"] or 0)), now))
            known[r["id"]] = (buy_c, to_milli(r["qty"] or 0))

        moves = conn.execute("SELECT id,pid,kind,qty,price,cost,date FROM legacy_moves ORDER BY id").fetchall()
        for m in moves:
            if m["kind"] not in ("sale", "purchase"):
                raise MigrationError(f"نوع حركة غير معروف في القاعدة القديمة: {m['kind']!r} (حركة رقم {m['id']})")
            if m["pid"] not in known:  # صنف اتحذف قبل كده: نعمله صنف أرشيف عشان التاريخ يفضل سليم
                conn.execute("INSERT INTO products(id,name,active,created_at) VALUES(?,?,0,?)",
                             (m["pid"], f"صنف محذوف #{m['pid']}", now))
                known[m["pid"]] = (0, 0)
            q = to_milli(m["qty"])
            if q == 0:
                continue
            date = m["date"] or OPENING_DATE
            if len(date) == 16:
                date += ":00"
            conn.execute("INSERT INTO stock_movements(product_id,warehouse_id,kind,qty_m,unit_price_c,unit_cost_c,"
                         "ref_type,note,created_at) VALUES(?,1,?,?,?,?,'legacy','حركة قديمة',?)",
                         (m["pid"], m["kind"], q if m["kind"] == "purchase" else -q,
                          to_cents(m["price"] or 0), to_cents(m["cost"] or 0), date))

        for pid, (buy_c, legacy_q) in known.items():  # رصيد افتتاحي يخلّي الرصيد = رصيد القاعدة القديمة بالظبط
            s = conn.execute("SELECT COALESCE(SUM(qty_m),0) FROM stock_movements WHERE product_id=?", (pid,)).fetchone()[0]
            diff = legacy_q - s
            if diff:
                has = conn.execute("SELECT 1 FROM stock_movements WHERE product_id=? LIMIT 1", (pid,)).fetchone()
                conn.execute("INSERT INTO stock_movements(product_id,warehouse_id,kind,qty_m,unit_price_c,unit_cost_c,"
                             "ref_type,note,created_at) VALUES(?,1,?,?,?,?,'legacy',?,?)",
                             (pid, "opening" if diff > 0 else "adjust", diff, buy_c, buy_c,
                              "رصيد افتتاحي من الترحيل" if diff > 0 else "تسوية ترحيل",
                              OPENING_DATE if has else now))

        report = build_report(before, snapshot_new(conn), backup)
        if not report["ok"]:
            raise MigrationError("أرقام الترحيل مش متطابقة، تم التراجع.\n" + report["text"], report)
        fk = conn.execute("PRAGMA foreign_key_check").fetchall()
        if fk:
            raise MigrationError(f"فيه مراجع غير سليمة بعد الترحيل: {[tuple(r) for r in fk]}", report)
        conn.execute("PRAGMA user_version = 1")
        conn.execute("COMMIT")
        return report
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
