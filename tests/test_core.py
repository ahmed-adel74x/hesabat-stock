import os, sqlite3, unittest
from decimal import Decimal
from helpers import tmp_db, make_legacy
from hesabat.db.connection import connect, tx
from hesabat.db.migrations import init_db, MigrationError
from hesabat.logic import inventory, products, warehouses, parties, reports
from hesabat.logic.errors import ValidationError
from hesabat.logic.money import parse_money, parse_qty, to_cents, fmt_money, fmt_qty, plain_money


def fresh():
    path = tmp_db()
    conn = connect(path)
    init_db(conn, path)
    return conn


class MoneyTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_money("12.5"), 1250)
        self.assertEqual(parse_money("١٢٫٥"), 1250)          # أرقام عربية
        self.assertEqual(parse_money("12,5"), 1250)
        self.assertEqual(to_cents(0.1 + 0.2), 30)              # مفيش خطأ float
        self.assertEqual(parse_qty("2.5"), 2500)
        for bad in ("abc", "-1", "", "1e5", "NaN"):
            with self.assertRaises(ValidationError):
                parse_money(bad)
        with self.assertRaises(ValidationError):
            parse_qty("0")
        self.assertEqual(parse_money("-5", allow_negative=True), -500)
        self.assertEqual(fmt_money(123456), "1,234.56")
        self.assertEqual(fmt_money(200000), "2,000")           # من غير .00
        self.assertEqual(fmt_money(1250), "12.50")             # القروش الحقيقية بتفضل
        self.assertEqual(fmt_money(0), "0")
        self.assertEqual(plain_money(200000), "2000")
        self.assertEqual(fmt_qty(2500), "2.5")
        self.assertEqual(fmt_qty(0), "0")


class MigrationTests(unittest.TestCase):
    def test_legacy_migration_matches(self):
        path = tmp_db(); make_legacy(path)
        conn = connect(path)
        rep = init_db(conn, path)
        self.assertTrue(rep["ok"], rep["text"])
        self.assertTrue(os.path.exists(rep["backup"]))
        self.assertTrue(os.path.exists(rep["report_file"]))
        self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 4)
        self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        # الأرصدة بعد الترحيل = الأرصدة القديمة بالظبط
        got = {r["id"]: r["qty_m"] for r in products.list_products(conn)}
        self.assertEqual(got, {1: 40000, 2: 3500, 4: -2000, 5: 0})
        # صنف محذوف اتحفظ كأرشيف وتاريخه سليم
        row = conn.execute("SELECT active FROM products WHERE id=99").fetchone()
        self.assertEqual(row["active"], 0)
        self.assertEqual(inventory.balance(conn, 99), 0)
        # الجداول القديمة محفوظة، والنسخة الاحتياطية فيها البيانات القديمة
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM legacy_products").fetchone()[0], 4)
        bk = sqlite3.connect(rep["backup"])
        self.assertEqual(bk.execute("SELECT COUNT(*) FROM products").fetchone()[0], 4)
        self.assertEqual(bk.execute("SELECT COUNT(*) FROM moves").fetchone()[0], 6)
        # الأسعار والتكلفة اتنقلت والتقرير شغال
        d = reports.dashboard(conn, today="2026-10-01")
        self.assertEqual(d["ts"], to_cents(Decimal("1.5") * Decimal("35.55")))
        self.assertEqual(d["tp"], to_cents(Decimal("1.5") * (Decimal("35.55") - Decimal("30.1"))))
        self.assertIn("متطابق", rep["text"])
        self.assertIsNone(init_db(conn, path))                 # التشغيل التاني مبيعملش حاجة

    def test_bad_data_rolls_back(self):
        path = tmp_db(); make_legacy(path, bad_kind=True)
        conn = connect(path)
        with self.assertRaises(MigrationError):
            init_db(conn, path)
        self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 0)
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual(names, {"products", "moves"})        # القاعدة زي ما كانت بالظبط
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM moves").fetchone()[0], 7)

    def test_fresh_db(self):
        conn = fresh()
        self.assertEqual(conn.execute("SELECT name FROM warehouses").fetchone()[0], "المخزن الرئيسي")
        self.assertEqual(conn.execute("SELECT is_default FROM customers WHERE id=1").fetchone()[0], 1)
        self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.c = fresh()
        self.pid = products.create(self.c, "سكر", "10", "15", "5", "10")   # 10 @ 10

    def test_weighted_average_and_cost_snapshot(self):
        c, pid = self.c, self.pid
        inventory.record_purchase(c, pid, 1, "10", "20")                    # (100+200)/20 = 15
        self.assertEqual(products.get(c, pid)["avg_cost_c"], 1500)
        sale1 = inventory.record_sale(c, pid, 1, "4", "18")
        inventory.record_purchase(c, pid, 1, "20", "30")                    # (16*15+20*30)/36 = 23.333
        self.assertEqual(products.get(c, pid)["avg_cost_c"], 2333)
        # حركة البيع القديمة محتفظة بتكلفتها وقت العملية (1500) مش بالمتوسط الجديد
        row = c.execute("SELECT unit_cost_c FROM stock_movements WHERE id=?", (sale1,)).fetchone()
        self.assertEqual(row[0], 1500)
        self.assertEqual(inventory.balance(c, pid), 36000)
        self.assertEqual(reports.dashboard(c)["tp"], 4 * (1800 - 1500))     # ربح 12.00 ثابت

    def test_set_quantity(self):
        c, pid = self.c, self.pid
        w2 = warehouses.create(c, "فرع")
        self.assertEqual(inventory.set_quantity(c, pid, 1, "25"), 15000)          # الفرق بيرجع
        self.assertEqual(inventory.balance(c, pid, 1), 25000)
        self.assertEqual(inventory.set_quantity(c, pid, 1, "7.5"), -17500)
        self.assertEqual(inventory.set_quantity(c, pid, 1, "7.5"), 0)             # نفس الكمية = مفيش حركة
        adj = c.execute("SELECT * FROM stock_movements WHERE kind='adjust' ORDER BY id").fetchall()
        self.assertEqual([r["qty_m"] for r in adj], [15000, -17500])
        self.assertEqual((adj[0]["ref_type"], adj[0]["unit_cost_c"]), ("manual", products.get(c, pid)["avg_cost_c"]))
        self.assertEqual(inventory.set_quantity(c, pid, w2, "4"), 4000)           # مخزن تاني مبيأثرش على الأول
        self.assertEqual((inventory.balance(c, pid, 1), inventory.balance(c, pid)), (7500, 11500))
        self.assertEqual(inventory.set_quantity(c, pid, 1, "0"), -7500)           # الصفر مسموح
        for bad in ("-1", "abc", ""):
            with self.assertRaises(ValidationError):
                inventory.set_quantity(c, pid, 1, bad)
        with self.assertRaises(ValidationError):
            inventory.set_quantity(c, 9999, 1, "1")
        with self.assertRaises(ValidationError):
            inventory.set_quantity(c, pid, 9999, "1")

    def test_update_product_with_quantity(self):
        c, pid = self.c, self.pid
        products.update(c, pid, "سكر ناعم", "10", "16", "5", "30")               # 10 -> 30 في المخزن الرئيسي
        self.assertEqual((inventory.balance(c, pid), products.get(c, pid)["name"]), (30000, "سكر ناعم"))
        n = c.execute("SELECT COUNT(*) FROM stock_movements").fetchone()[0]
        products.update(c, pid, "سكر ناعم", "10", "17", "5")                      # من غير كمية: مفيش حركة
        products.update(c, pid, "سكر ناعم", "10", "17", "5", "")                  # فاضية = مفيش تغيير
        self.assertEqual(c.execute("SELECT COUNT(*) FROM stock_movements").fetchone()[0], n)
        w2 = warehouses.create(c, "فرع")
        products.update(c, pid, "سكر ناعم", "10", "17", "5", "8", w2)             # كمية المخزن التاني
        self.assertEqual((inventory.balance(c, pid, 1), inventory.balance(c, pid, w2)), (30000, 8000))
        for bad in ("abc", "-5"):                                                  # كمية غلط: مفيش تعديل جزئي حتى للاسم
            with self.assertRaises(ValidationError):
                products.update(c, pid, "اسم جديد", "10", "17", "5", bad)
            self.assertEqual(products.get(c, pid)["name"], "سكر ناعم")

    def test_sale_blocked_without_stock(self):
        with self.assertRaises(ValidationError) as cm:
            inventory.record_sale(self.c, self.pid, 1, "11")
        self.assertIn("المتاح", str(cm.exception))
        self.assertEqual(inventory.balance(self.c, self.pid), 10000)

    def test_transfer_and_atomicity(self):
        c, pid = self.c, self.pid
        w2 = warehouses.create(c, "فرع", "القاهرة")
        p2 = products.create(c, "شاي", "5", "7", "0", "3")
        inventory.transfer(c, 1, w2, [(pid, "4")])
        self.assertEqual(inventory.balance(c, pid, 1), 6000)
        self.assertEqual(inventory.balance(c, pid, w2), 4000)
        self.assertEqual(inventory.balance(c, pid), 10000)                  # الإجمالي ثابت
        before = c.execute("SELECT COUNT(*) FROM stock_movements").fetchone()[0]
        with self.assertRaises(ValidationError):                            # الصنف التاني رصيده مش كفاية
            inventory.transfer(c, 1, w2, [(pid, "1"), (p2, "99")])
        self.assertEqual(c.execute("SELECT COUNT(*) FROM stock_movements").fetchone()[0], before)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM stock_transfers").fetchone()[0], 1)
        with self.assertRaises(ValidationError):
            inventory.transfer(c, 1, 1, [(pid, "1")])

    def test_stocktake(self):
        c, pid = self.c, self.pid
        sid, changed = inventory.apply_stocktake(c, 1, {pid: "7.5"})
        self.assertEqual((changed), 1)
        self.assertEqual(inventory.balance(c, pid, 1), 7500)
        item = c.execute("SELECT * FROM stocktake_items WHERE stocktake_id=?", (sid,)).fetchone()
        self.assertEqual((item["system_qty_m"], item["counted_qty_m"], item["diff_qty_m"]), (10000, 7500, -2500))
        self.assertEqual(inventory.apply_stocktake(c, 1, {pid: "7.5"})[1], 0)   # مفيش فرق
        with self.assertRaises(ValidationError):
            inventory.apply_stocktake(c, 1, {pid: "-1"})

    def test_product_rules(self):
        with self.assertRaises(ValidationError):
            products.create(self.c, "سكر", "1", "2")                        # مكرر
        with self.assertRaises(ValidationError):
            products.create(self.c, "  ", "1", "2")
        with self.assertRaises(ValidationError):
            products.create(self.c, "x", "-1", "2")
        products.deactivate(self.c, self.pid)
        self.assertEqual(products.list_products(self.c), [])

    def test_warehouse_rules(self):
        c = self.c
        with self.assertRaises(ValidationError):
            warehouses.deactivate(c, 1)                                      # آخر مخزن
        w2 = warehouses.create(c, "فرع")
        with self.assertRaises(ValidationError):
            warehouses.deactivate(c, 1)                                      # فيه أرصدة
        with self.assertRaises(ValidationError):
            warehouses.create(c, "فرع")
        warehouses.deactivate(c, w2)


class PartyTests(unittest.TestCase):
    def test_statement(self):
        c = fresh()
        sid = parties.create(c, "supplier", "مورد 1", "010", opening_balance="500")
        parties.add_ledger_entry(c, "supplier", sid, "invoice", 20000, note="فاتورة 1")
        parties.add_ledger_entry(c, "supplier", sid, "payment", -12000)
        st = parties.statement(c, "supplier", sid)
        self.assertEqual([r[4] for r in st["rows"]], [50000, 70000, 58000])
        self.assertEqual(st["balance_c"], 58000)
        self.assertEqual(parties.list_parties(c, "supplier")[0]["balance_c"], 58000)

    def test_default_customer_protected(self):
        c = fresh()
        with self.assertRaises(ValidationError):
            parties.deactivate(c, "customer", 1)
        cid = parties.create(c, "customer", "أحمد", opening_balance="-100")
        bal = {r["name"]: r["balance_c"] for r in parties.list_parties(c, "customer")}
        self.assertEqual(bal["أحمد"], -10000)
        with self.assertRaises(ValidationError):
            parties.create(c, "customer", "أحمد")


class TxTests(unittest.TestCase):
    def test_rollback(self):
        c = fresh()
        with self.assertRaises(RuntimeError):
            with tx(c):
                c.execute("INSERT INTO warehouses(name,created_at) VALUES('x','now')")
                raise RuntimeError
        self.assertEqual(c.execute("SELECT COUNT(*) FROM warehouses").fetchone()[0], 1)


class PreferencesTests(unittest.TestCase):
    def test_theme_persists(self):
        from hesabat.logic import preferences
        from hesabat.ui.theme import build_style, PALETTES
        path = tmp_db()
        c = connect(path); init_db(c, path)
        self.assertEqual(preferences.get_theme(c), "light")
        preferences.set_theme(c, "dark"); preferences.set_theme(c, "dark")
        self.assertEqual(preferences.get_theme(c), "dark")
        with self.assertRaises(ValueError):
            preferences.set_theme(c, "blue")
        c.close()
        for mode in PALETTES:
            self.assertNotIn("%(", build_style(mode))
        self.assertNotEqual(build_style("light"), build_style("dark"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
