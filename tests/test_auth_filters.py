import unittest
from helpers import tmp_db
from hesabat.db.connection import connect
from hesabat.db.migrations import init_db
from hesabat.logic import auth, invoices, parties, party_reports, products, treasury, warehouses
from hesabat.logic.errors import ValidationError


def fresh():
    p = tmp_db(); c = connect(p); init_db(c, p); return c


class Auth(unittest.TestCase):
    def test_default_and_change(self):
        c = fresh()
        self.assertTrue(auth.verify(c, "marko", "12345"))
        self.assertTrue(auth.verify(c, " Marko ", "12345"))
        self.assertFalse(auth.verify(c, "marko", "1234"))
        self.assertFalse(auth.verify(c, "x", "12345"))
        self.assertNotIn("12345", [r[0] for r in c.execute("SELECT value FROM app_settings")])   # مش متخزنة نص
        with self.assertRaises(ValidationError): auth.change_password(c, "bad", "abcd", "abcd")
        with self.assertRaises(ValidationError): auth.change_password(c, "12345", "abcd", "abce")
        with self.assertRaises(ValidationError): auth.change_password(c, "12345", "ab", "ab")
        auth.change_password(c, "12345", "newpass", "newpass")
        self.assertFalse(auth.verify(c, "marko", "12345"))
        self.assertTrue(auth.verify(c, "marko", "newpass"))
        with self.assertRaises(ValidationError): auth.change_name(c, "wrong", "ahmed")
        auth.change_name(c, "newpass", "ahmed")
        self.assertEqual(auth.admin_name(c), "ahmed")
        self.assertTrue(auth.verify(c, "ahmed", "newpass"))


class Data(unittest.TestCase):
    def setUp(self):
        c = self.c = fresh()
        self.p = products.create(c, "سكر", "15", "10", "100", "0") if False else None
        from hesabat.logic import inventory
        self.pid = c.execute("INSERT INTO products(name,sell_price_c,buy_price_c,avg_cost_c,created_at) "
                             "VALUES('سكر',1500,1000,1000,'x')").lastrowid
        inventory.add_movement(c, self.pid, 1, "opening", 1000000, 0, 1000, None, None, "", "2026-01-01 00:00:00")
        self.ali = parties.create(c, "customer", "علي محمد", "0100")
        self.omar = parties.create(c, "customer", "عمر أحمد", "0111")
        self.sup = parties.create(c, "supplier", "مورد النور")

    def sale(self, cust, qty, paid, date):
        return invoices.create_invoice(self.c, "sale", cust, 1, [(self.pid, qty, "15")], "0", paid, "", date)

    def test_party_search(self):
        rows = parties.list_parties(self.c, "customer")
        self.assertEqual([r["name"] for r in parties.search(rows, "علي")], ["علي محمد"])
        self.assertEqual([r["name"] for r in parties.search(rows, "0111")], ["عمر أحمد"])      # بالتليفون
        self.assertEqual([r["name"] for r in parties.search(rows, "احمد عمر")], ["عمر أحمد"])  # أ/ا وترتيب الكلمات
        self.assertEqual(len(parties.search(rows, "")), 3)                                      # شامل العميل النقدي
        self.assertEqual(parties.search(rows, "مفيش"), [])

    def test_invoice_filters(self):
        a = self.sale(self.ali, "2", "10", "2026-09-01")      # 30، مدفوع 10
        b = self.sale(self.omar, "1", "15", "2026-10-05")     # 15 مسدد
        c3 = self.sale(self.ali, "1", "0", "2026-10-10")      # 15 غير مدفوع
        L = lambda **k: [r["id"] for r in invoices.list_invoices(self.c, "sale", **k)]
        self.assertEqual(L(), [c3, b, a])
        self.assertEqual(L(number="2"), [b])
        self.assertEqual(L(number="٣"), [c3])                  # أرقام عربية
        self.assertEqual(L(party="علي"), [c3, a])
        self.assertEqual(L(date_from="2026-10-01"), [c3, b])
        self.assertEqual(L(date_to="2026-09-30"), [a])
        self.assertEqual(L(date_from="2026-10-06", date_to="2026-10-31"), [c3])
        self.assertEqual(L(unpaid_only=True), [c3, a])
        self.assertEqual(L(party="علي", unpaid_only=True, date_from="2026-10-01"), [c3])
        self.assertEqual(L(number="99"), [])
        for bad in (dict(number="abc"), dict(date_from="غلط"), dict(date_from="2026-10-10", date_to="2026-01-01")):
            with self.assertRaises(ValidationError): L(**bad)

    def test_invoice_print_shows_total_owed(self):
        a = self.sale(self.ali, "2", "10", "2026-09-01")       # باقي 20
        b = self.sale(self.ali, "1", "0", "2026-10-10")        # باقي 15 => إجمالي 35
        h = invoices.invoice_html(self.c, b)
        self.assertIn("إجمالي المتبقي على العميل", h)
        self.assertIn("35", h)
        cash = parties.default_customer_id(self.c)
        c3 = self.sale(cash, "1", "15", "2026-10-11")
        self.assertNotIn("إجمالي المتبقي", invoices.invoice_html(self.c, c3))   # العميل النقدي: مفيش
        treasury.add_entry(self.c, "receipt", 3500, "customer", self.ali, note="سداد")
        self.assertIn("مسدّد بالكامل", invoices.invoice_html(self.c, b))
        sup_inv = invoices.create_invoice(self.c, "purchase", self.sup, 1, [(self.pid, "1", "10")], "0", "0")
        self.assertIn("إجمالي المتبقي للمورد", invoices.invoice_html(self.c, sup_inv))

    def test_party_reports_reconcile(self):
        parties.update(self.c, "customer", self.ali, "علي محمد", "0100", "", "", "50")       # افتتاحي 50
        self.sale(self.ali, "2", "10", "2026-09-01")            # +30 -10  => 20
        b = self.sale(self.ali, "1", "0", "2026-10-10")         # +15
        treasury.add_entry(self.c, "receipt", 500, "customer", self.ali, note="دفعة مستقلة")  # -5
        invoices.create_invoice(self.c, "sale_return", self.ali, 1, [(self.pid, "1", "15")], "0", "0")  # -15
        data = party_reports.dues_data(self.c, "customer", self.ali)
        bal = parties.balance(self.c, "customer", self.ali)
        self.assertEqual(bal, 5000 + 2000 + 1500 - 500 - 1500)
        self.assertEqual(data[4], 0)                              # مفيش تسويات غير مفسّرة
        self.assertEqual(data[5], bal)
        h = party_reports.dues_html(self.c, "customer", self.ali)
        self.assertIn("فاتورة بيع رقم 1", h); self.assertIn("مرتجع مبيعات رقم 1", h); self.assertIn("دفعة مستقلة", h)
        self.assertIn("رصيد افتتاحي", h); self.assertIn("65", h)
        self.assertIn("سكر × 2", h)                                   # الصنف ظاهر جنب الفاتورة
        full = party_reports.statement_html(self.c, "customer", self.ali)
        self.assertIn("سكر × 2", full); self.assertIn("الأصناف", full)
        self.assertIn("تفاصيل الفواتير", full); self.assertIn("سكر", full); self.assertIn("65", full)
        # بعد تعديل ومسح فاتورة لسه الإجمالي يطابق الرصيد
        invoices.update_invoice(self.c, b, self.ali, 1, [(self.pid, "3", "15")], "0", "5", "", "2026-10-10")
        invoices.delete_invoice(self.c, 1)
        bal = parties.balance(self.c, "customer", self.ali)
        d = party_reports.dues_data(self.c, "customer", self.ali)
        self.assertEqual((d[4], d[5]), (0, bal))
        self.assertNotIn("فاتورة بيع رقم 1<", party_reports.dues_html(self.c, "customer", self.ali))
        party_reports.statement_html(self.c, "supplier", self.sup)       # مورد من غير فواتير: مفيش خطأ


    def test_remove_cancelled_rows(self):
        a = self.sale(self.ali, "2", "10", "2026-09-01")
        invoices.update_invoice(self.c, a, self.ali, 1, [(self.pid, "3", "15")], "0", "20", "", "2026-09-01")   # تعديل: بيسيب أسطر ملغية
        st = parties.statement(self.c, "customer", self.ali)
        ids = [i for i, r in zip(st["ledger_ids"], st["removable"]) if r]
        self.assertGreaterEqual(len(ids), 4)                      # فاتورة قديمة + إلغاءها + دفعة قديمة + إلغاءها
        live = [i for i, r in zip(st["ledger_ids"], st["removable"]) if i and not r]
        self.assertEqual(len(live), 2)                            # الفاتورة الجديدة ودفعتها
        bal = parties.balance(self.c, "customer", self.ali)
        while ids:
            parties.remove_cancelled(self.c, "customer", self.ali, ids[0])
            st = parties.statement(self.c, "customer", self.ali)
            ids = [i for i, r in zip(st["ledger_ids"], st["removable"]) if r]
        self.assertEqual(parties.balance(self.c, "customer", self.ali), bal)   # الرصيد زي ما هو
        self.assertEqual(len(st["rows"]), 3)                      # افتتاحي + الفاتورة + الدفعة
        with self.assertRaises(ValidationError): parties.remove_cancelled(self.c, "customer", self.ali, live[0])


if __name__ == "__main__":
    unittest.main()
