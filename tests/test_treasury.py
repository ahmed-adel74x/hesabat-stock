import os, unittest
from datetime import datetime, timedelta
from helpers import tmp_db, make_v1
from hesabat.db.connection import connect
from hesabat.db.migrations import init_db
from hesabat.logic import parties, treasury as tr
from hesabat.logic.errors import ValidationError


def day(n):
    return (datetime.now() - timedelta(days=n)).strftime("%Y-%m-%d")


def fresh():
    path = tmp_db(); conn = connect(path); init_db(conn, path)
    return conn


class UpgradeTests(unittest.TestCase):
    def test_v1_to_v2_keeps_data(self):
        path = tmp_db(); make_v1(path)
        conn = connect(path)
        self.assertIsNone(init_db(conn, path))
        self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 3)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM invoices").fetchone()[0], 0)
        self.assertEqual(conn.execute("SELECT SUM(qty_m) FROM stock_movements").fetchone()[0], 5000)
        self.assertEqual(conn.execute("SELECT name FROM products").fetchone()[0], "سكر")
        self.assertEqual(tr.get_opening(conn), 0)
        backups = os.listdir(os.path.join(os.path.dirname(path), "backups"))
        self.assertTrue(any("before_v2" in b for b in backups) and any("before_v3" in b for b in backups))
        self.assertIsNone(init_db(conn, path))                      # التشغيل التاني مبيعملش حاجة

    def test_fresh_is_latest(self):
        self.assertEqual(fresh().execute("PRAGMA user_version").fetchone()[0], 3)


class TreasuryTests(unittest.TestCase):
    def setUp(self):
        self.c = fresh()
        tr.set_opening(self.c, "1000")

    def test_balance_and_links(self):
        c = self.c
        cust = parties.create(c, "customer", "أحمد", opening_balance="500")
        sup = parties.create(c, "supplier", "مورد", opening_balance="800")
        tr.add_voucher(c, "receipt", "200", "customer", cust)         # تحصيل
        tr.add_voucher(c, "payment", "300", "supplier", sup)          # سداد
        tr.add_voucher(c, "payment", "50", category="كهرباء")         # مصروف عام
        tr.add_voucher(c, "receipt", "25.5", category="إيراد آخر")
        self.assertEqual(tr.balance(c), 100000 + 20000 - 30000 - 5000 + 2550)
        bal = lambda k, i: {r["id"]: r["balance_c"] for r in parties.list_parties(c, k)}[i]
        self.assertEqual(bal("customer", cust), 30000)                 # 500 - 200
        self.assertEqual(bal("supplier", sup), 50000)                  # 800 - 300
        # استرداد: صرف لعميل بيزوّد اللي عليه، وقبض من مورد بيزوّد اللي له
        tr.add_voucher(c, "payment", "10", "customer", cust)
        tr.add_voucher(c, "receipt", "10", "supplier", sup)
        self.assertEqual(bal("customer", cust), 31000)
        self.assertEqual(bal("supplier", sup), 51000)

    def test_validation_and_atomicity(self):
        c = self.c
        for bad in ("0", "-5", "abc", ""):
            with self.assertRaises(ValidationError):
                tr.add_voucher(c, "receipt", bad, category="x")
        with self.assertRaises(ValidationError):
            tr.add_voucher(c, "payment", "5")                          # عام من غير بيان
        with self.assertRaises(ValidationError):
            tr.add_voucher(c, "payment", "5", category="x", entry_date=day(-3))   # مستقبل
        with self.assertRaises(ValidationError):
            tr.add_voucher(c, "payment", "5", category="x", entry_date="مش تاريخ")
        with self.assertRaises(ValidationError):
            tr.add_voucher(c, "payment", "5", "supplier", 999)         # طرف مش موجود
        self.assertEqual(c.execute("SELECT COUNT(*) FROM treasury_entries").fetchone()[0], 0)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM party_ledger").fetchone()[0], 0)
        tr.add_voucher(c, "receipt", "5", category="x", entry_date="٢٠٢٦/١٠/٠١")   # أرقام عربية و /

    def test_statement_running_balance(self):
        c = self.c
        tr.add_voucher(c, "receipt", "100", category="a", entry_date=day(5))
        tr.add_voucher(c, "payment", "30", category="b", entry_date=day(3))
        tr.add_voucher(c, "receipt", "50", category="c", entry_date=day(1))
        full = tr.statement(c)
        self.assertEqual([r["running_c"] for r in full["rows"]], [110000, 107000, 112000])
        part = tr.statement(c, day(3), day(1))
        self.assertEqual(part["opening_c"], 110000)                    # الرصيد قبل بداية الفترة
        self.assertEqual((part["total_in"], part["total_out"], part["closing_c"]), (5000, 3000, 112000))
        self.assertEqual(tr.statement(c, day(0), day(0))["rows"], [])
        with self.assertRaises(ValidationError):
            tr.statement(c, day(1), day(5))

    def test_void_reverses(self):
        c = self.c
        cust = parties.create(c, "customer", "أحمد", opening_balance="500")
        eid = tr.add_voucher(c, "receipt", "200", "customer", cust)
        tr.void_entry(c, eid)
        self.assertEqual(tr.balance(c), 100000)
        self.assertEqual([r["balance_c"] for r in parties.list_parties(c, "customer") if r["id"] == cust][0], 50000)
        with self.assertRaises(ValidationError):
            tr.void_entry(c, eid)                                      # ملغي بالفعل
        inv = tr.add_entry(c, "receipt", 1000, ref_type="invoice", ref_id=7, category="فاتورة")
        with self.assertRaises(ValidationError):
            tr.void_entry(c, inv)                                      # مرتبط بفاتورة
        with self.assertRaises(ValidationError):
            tr.void_entry(c, 99999)

    def test_close_day_locks_and_adjusts(self):
        c = self.c
        tr.add_voucher(c, "receipt", "100", category="a", entry_date=day(4))
        tr.add_voucher(c, "payment", "40", category="b", entry_date=day(3))
        cid = tr.close_day(c, day(3), counted="1050")                  # الدفتري 1060، الفعلي 1050 => عجز 10
        row = c.execute("SELECT * FROM treasury_closings WHERE id=?", (cid,)).fetchone()
        self.assertEqual((row["opening_c"], row["receipts_c"], row["payments_c"], row["closing_c"], row["diff_c"]),
                         (100000, 10000, 5000, 105000, -1000))
        self.assertEqual(tr.balance(c), 105000)                        # الدفتري بقى = الفعلي
        with self.assertRaises(ValidationError):
            tr.add_voucher(c, "receipt", "1", category="x", entry_date=day(3))   # مقفول
        with self.assertRaises(ValidationError):
            tr.add_voucher(c, "receipt", "1", category="x", entry_date=day(4))
        adj = c.execute("SELECT id FROM treasury_entries WHERE ref_type='closing'").fetchone()[0]
        with self.assertRaises(ValidationError):
            tr.void_entry(c, adj)
        with self.assertRaises(ValidationError):
            tr.close_day(c, day(3))                                    # مقفول بالفعل
        with self.assertRaises(ValidationError):
            tr.set_opening(c, "5")
        tr.add_voucher(c, "receipt", "20", category="x", entry_date=day(2))      # بعد التقفيل تمام
        c2 = tr.close_day(c, day(1))
        r2 = c.execute("SELECT * FROM treasury_closings WHERE id=?", (c2,)).fetchone()
        self.assertEqual((r2["opening_c"], r2["receipts_c"], r2["closing_c"]), (105000, 2000, 107000))
        with self.assertRaises(ValidationError):
            tr.close_day(c, day(-1))                                   # تقفيل مستقبلي
        self.assertEqual(tr.reopen_last_closing(c), day(1))
        self.assertEqual(tr.reopen_last_closing(c), day(3))
        self.assertEqual(tr.balance(c), 108000)                        # 1000+100-40+20 (تسوية العجز اتلغت)
        tr.add_voucher(c, "receipt", "1", category="x", entry_date=day(3))        # اتفتح تاني
        tr.set_opening(c, "5")
        with self.assertRaises(ValidationError):
            tr.reopen_last_closing(c)


if __name__ == "__main__":
    unittest.main(verbosity=2)
