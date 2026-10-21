import unittest
from helpers import tmp_db
from hesabat.db.connection import connect
from hesabat.db.migrations import init_db
from hesabat.logic import inventory, invoices as inv, parties, products, reports, treasury as tr
from hesabat.logic.errors import ValidationError


class SalesBase(unittest.TestCase):
    def setUp(self):
        path = tmp_db(); self.c = connect(path); init_db(self.c, path)
        self.cust = parties.create(self.c, "customer", "أحمد", opening_balance="50")
        self.cash = parties.default_customer_id(self.c)
        self.sugar = products.create(self.c, "سكر", "10", "15", "0", "10")      # 10 @ 10، سعر بيع 15

    def cust_bal(self, cid=None):
        cid = cid or self.cust
        return {r["id"]: r["balance_c"] for r in parties.list_parties(self.c, "customer")}[cid]

    def stock(self):
        return inventory.balance(self.c, self.sugar, 1)

    def sell(self, items=None, discount="0", paid="0", cust=None, date=None, kind="sale"):
        if items is None:
            items = [(self.sugar, "4", "20")]
        return inv.create_invoice(self.c, kind, cust or self.cust, 1, items, discount, paid, "", date)


class SaleTests(SalesBase):
    def test_default_customer_exists(self):
        self.assertEqual(self.c.execute("SELECT name FROM customers WHERE id=?", (self.cash,)).fetchone()[0], "عميل نقدي")

    def test_effects(self):
        iid = self.sell(discount="10", paid="30")                    # 4 × 20 = 80 - 10 = 70
        h = inv.get_invoice(self.c, iid)["invoice"]
        self.assertEqual((h["kind"], h["number"], h["total_c"], h["paid_c"]), ("sale", 1, 7000, 3000))
        self.assertEqual(self.stock(), 6000)
        self.assertEqual(self.cust_bal(), 5000 + 7000 - 3000)        # 50 + 70 - 30
        self.assertEqual(tr.balance(self.c), 3000)                   # تحصيل داخل الخزينة
        e = self.c.execute("SELECT * FROM treasury_entries").fetchone()
        self.assertEqual((e["kind"], e["ref_type"], e["ref_id"]), ("receipt", "invoice", iid))
        m = self.c.execute("SELECT * FROM stock_movements WHERE ref_type='invoice'").fetchone()
        self.assertEqual((m["kind"], m["qty_m"], m["unit_price_c"], m["unit_cost_c"]), ("sale", -4000, 1750, 1000))
        d = reports.dashboard(self.c)
        self.assertEqual((d["ts"], d["tp"]), (7000, 4 * (1750 - 1000)))        # ربح 30.00
        self.assertEqual(inv.default_price(self.c, "sale", self.sugar), 1500)   # سعر البيع الافتراضي

    def test_blocked_when_not_enough(self):
        with self.assertRaises(ValidationError) as cm:
            self.sell(items=[(self.sugar, "11", "20")])
        self.assertIn("الكمية المتاحة", str(cm.exception))
        with self.assertRaises(ValidationError):                      # سطرين لنفس الصنف مجموعهم أكبر من المتاح
            self.sell(items=[(self.sugar, "6", "20"), (self.sugar, "6", "20")], paid="0")
        self.assertEqual(self.stock(), 10000)
        for t in ("invoices", "invoice_items", "treasury_entries", "party_ledger"):
            self.assertEqual(self.c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0], 0, t)

    def test_cash_customer_must_pay_full(self):
        with self.assertRaises(ValidationError) as cm:
            self.sell(cust=self.cash, paid="10")
        self.assertIn("العميل النقدي", str(cm.exception))
        self.assertEqual(self.stock(), 10000)
        self.sell(cust=self.cash, paid="80")                          # كامل المبلغ
        self.assertEqual(self.cust_bal(self.cash), 0)
        self.assertEqual(tr.balance(self.c), 8000)

    def test_profit_uses_cost_at_time_of_sale(self):
        self.sell()                                                   # تكلفة 10
        sup = parties.create(self.c, "supplier", "مورد")
        inv.create_invoice(self.c, "purchase", sup, 1, [(self.sugar, "10", "50")])   # المتوسط يتغير
        self.assertEqual(reports.dashboard(self.c)["tp"], 4 * (2000 - 1000))

    def test_update_sale(self):
        iid = self.sell(paid="20")                                    # 80، رصيد 6
        inv.update_invoice(self.c, iid, self.cust, 1, [(self.sugar, "10", "15")], "0", "50")   # 150 كاملة المخزون
        h = inv.get_invoice(self.c, iid)["invoice"]
        self.assertEqual((h["total_c"], h["paid_c"], h["number"]), (15000, 5000, 1))
        self.assertEqual(self.stock(), 0)
        self.assertEqual(self.cust_bal(), 5000 + 15000 - 5000)
        self.assertEqual(tr.balance(self.c), 5000)                    # دفعة قديمة اتلغت والجديدة اتسجلت
        with self.assertRaises(ValidationError):                      # أكتر من الموجود (10)
            inv.update_invoice(self.c, iid, self.cust, 1, [(self.sugar, "11", "15")])
        self.assertEqual(inv.get_invoice(self.c, iid)["invoice"]["total_c"], 15000)       # اتراجع كله
        self.assertEqual(self.stock(), 0)
        self.assertEqual(self.cust_bal(), 15000)

    def test_cancel_sale_restores_everything(self):
        iid = self.sell(paid="30")
        inv.cancel_invoice(self.c, iid)
        self.assertEqual(self.stock(), 10000)
        self.assertEqual(self.cust_bal(), 5000)
        self.assertEqual(tr.balance(self.c), 0)
        d = reports.dashboard(self.c)
        self.assertEqual((d["ts"], d["tp"]), (0, 0))                  # المبيعات والربح اتعادلوا
        with self.assertRaises(ValidationError):
            inv.cancel_invoice(self.c, iid)

    def test_numbering_per_kind_and_list(self):
        self.sell(); self.sell()
        self.assertEqual([r["number"] for r in inv.list_invoices(self.c, "sale")], [2, 1])
        self.sell(kind="sale_return", items=[(self.sugar, "1", "20")])
        self.assertEqual(inv.list_invoices(self.c, "sale_return")[0]["number"], 1)
        self.assertEqual(inv.list_invoices(self.c, "sale")[0]["party_name"], "أحمد")


class SaleReturnTests(SalesBase):
    def test_return_effects_and_net_reports(self):
        self.sell(items=[(self.sugar, "4", "20")], paid="0")          # بيع 80، الرصيد 6
        rid = self.sell(items=[(self.sugar, "1", "20")], kind="sale_return", paid="5")   # مرتجع 20، رجّعنا 5 نقدي
        self.assertEqual(self.stock(), 7000)
        self.assertEqual(self.cust_bal(), 5000 + 8000 - 2000 + 500)   # 50 + 80 - 20 + 5
        self.assertEqual(tr.balance(self.c), -500)
        d = reports.dashboard(self.c)
        self.assertEqual((d["ts"], d["tp"]), (6000, 3000))          # صافي المبيعات 60، صافي الربح 30
        inv.cancel_invoice(self.c, rid)
        self.assertEqual(self.stock(), 6000)
        self.assertEqual(self.cust_bal(), 13000)
        self.assertEqual(tr.balance(self.c), 0)
        self.assertEqual(reports.dashboard(self.c)["ts"], 8000)

    def test_cash_customer_return_must_refund_all(self):
        with self.assertRaises(ValidationError):
            self.sell(items=[(self.sugar, "1", "20")], kind="sale_return", cust=self.cash, paid="0")
        self.sell(items=[(self.sugar, "1", "20")], kind="sale_return", cust=self.cash, paid="20")
        self.assertEqual(self.cust_bal(self.cash), 0)

    def test_cannot_cancel_return_if_resold(self):
        rid = self.sell(items=[(self.sugar, "2", "20")], kind="sale_return")          # الرصيد 12
        self.sell(items=[(self.sugar, "11", "20")])                                    # باع منها لحد ما بقى 1
        with self.assertRaises(ValidationError) as cm:
            inv.cancel_invoice(self.c, rid)
        self.assertIn("اتباعت", str(cm.exception))
        self.assertEqual(inv.get_invoice(self.c, rid)["invoice"]["status"], "active")
        self.assertEqual(self.stock(), 1000)

    def test_update_return(self):
        rid = self.sell(items=[(self.sugar, "2", "20")], kind="sale_return")          # 12
        inv.update_invoice(self.c, rid, self.cust, 1, [(self.sugar, "5", "20")])
        self.assertEqual(self.stock(), 15000)
        self.assertEqual(self.cust_bal(), 5000 - 10000)


class DeleteSaleTests(SalesBase):
    def numbers(self):
        return (self.stock(), self.cust_bal(), tr.balance(self.c), reports.dashboard(self.c)["ts"], reports.dashboard(self.c)["tp"])

    def test_delete_sale(self):
        before = self.numbers()
        iid = self.sell(discount="10", paid="30")
        inv.delete_invoice(self.c, iid)
        self.assertEqual(self.numbers(), before)                        # المخزون وحساب العميل والخزينة والمبيعات والربح
        self.assertEqual(inv.list_invoices(self.c, "sale"), [])
        for t in ("invoices", "invoice_items", "party_ledger", "treasury_entries"):
            self.assertEqual(self.c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0], 0, t)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM stock_movements WHERE ref_type='invoice'").fetchone()[0], 0)
        self.assertEqual(len(parties.statement(self.c, "customer", self.cust)["rows"]), 1)

    def test_delete_sale_return_and_keeps_others(self):
        sale = self.sell(paid="0")
        before = self.numbers()
        rid = self.sell(items=[(self.sugar, "1", "20")], kind="sale_return", paid="5")
        inv.delete_invoice(self.c, rid)
        self.assertEqual(self.numbers(), before)
        self.assertEqual([r["id"] for r in inv.list_invoices(self.c, "sale")], [sale])

    def test_delete_blocked_when_return_cannot_be_reversed(self):
        rid = self.sell(items=[(self.sugar, "2", "20")], kind="sale_return")
        self.sell(items=[(self.sugar, "11", "20")])
        with self.assertRaises(ValidationError):
            inv.delete_invoice(self.c, rid)
        self.assertEqual(len(inv.list_invoices(self.c, "sale_return")), 1)


class HtmlTests(SalesBase):
    def test_invoice_html(self):
        p = products.create(self.c, "<b>زيت</b>", "5", "9", "0", "10")
        iid = self.sell(items=[(p, "2", "9"), (self.sugar, "1", "15")], discount="3", paid="10")
        h = inv.invoice_html(self.c, iid, shop_name="محل الأمل")
        for s in ("فاتورة بيع رقم 1", "أحمد", "محل الأمل", "المخزن الرئيسي", "33", "3", "30", "10", "20"):
            self.assertIn(s, h)
        self.assertIn("&lt;b&gt;زيت&lt;/b&gt;", h)                    # الأسماء بتتعمل escape
        self.assertNotIn("<b>زيت</b>", h)
        inv.cancel_invoice(self.c, iid)
        self.assertIn("(ملغية)", inv.invoice_html(self.c, iid))


if __name__ == "__main__":
    unittest.main(verbosity=2)
