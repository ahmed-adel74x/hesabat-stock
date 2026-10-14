import unittest
from datetime import datetime, timedelta
from helpers import tmp_db
from hesabat.db.connection import connect
from hesabat.db.migrations import init_db
from hesabat.logic import inventory, invoices as inv, parties, products, treasury as tr
from hesabat.logic.errors import ValidationError


def day(n):
    return (datetime.now() - timedelta(days=n)).strftime("%Y-%m-%d")


class InvoiceBase(unittest.TestCase):
    def setUp(self):
        path = tmp_db(); self.c = connect(path); init_db(self.c, path)
        self.sup = parties.create(self.c, "supplier", "مورد", opening_balance="100")
        self.sugar = products.create(self.c, "سكر", "10", "15", "0", "10")        # 10 @ 10
        self.tea = products.create(self.c, "شاي", "5", "7", "0", "0")

    def sup_bal(self):
        return {r["id"]: r["balance_c"] for r in parties.list_parties(self.c, "supplier")}[self.sup]

    def bal(self, pid, wid=1):
        return inventory.balance(self.c, pid, wid)

    def make(self, items=None, discount="0", paid="0", date=None, kind="purchase"):
        if items is None:
            items = [(self.sugar, "10", "20")]
        return inv.create_invoice(self.c, kind, self.sup, 1, items, discount, paid, "", date)


class PurchaseTests(InvoiceBase):
    def test_create_effects(self):
        iid = self.make(discount="20", paid="80")                    # 200 - 20 = 180
        data = inv.get_invoice(self.c, iid)
        h = data["invoice"]
        self.assertEqual((h["number"], h["subtotal_c"], h["discount_c"], h["total_c"], h["paid_c"]),
                         (1, 20000, 2000, 18000, 8000))
        self.assertEqual(self.bal(self.sugar), 20000)                # 10 + 10
        self.assertEqual(self.sup_bal(), 10000 + 18000 - 8000)       # 100 + 180 - 80
        self.assertEqual(tr.balance(self.c), -8000)                  # دفعة خارجة من الخزينة
        e = self.c.execute("SELECT * FROM treasury_entries").fetchone()
        self.assertEqual((e["kind"], e["amount_c"], e["ref_type"], e["ref_id"]), ("payment", 8000, "invoice", iid))
        self.assertEqual(inv.list_invoices(self.c, "purchase")[0]["remaining_c"], 10000)
        self.make()
        self.assertEqual(inv.get_invoice(self.c, self.make())["invoice"]["number"], 3)   # ترقيم متسلسل

    def test_discount_goes_into_average_cost(self):
        self.make(discount="40")                                     # 200-40 = 160 => 16 للوحدة
        p = products.get(self.c, self.sugar)
        self.assertEqual(p["avg_cost_c"], 1300)                      # (10*10 + 10*16) / 20
        self.assertEqual(p["buy_price_c"], 2000)                     # آخر سعر مكتوب
        m = self.c.execute("SELECT unit_price_c,unit_cost_c,created_at FROM stock_movements WHERE ref_type='invoice'").fetchone()
        self.assertEqual((m["unit_price_c"], m["unit_cost_c"]), (1600, 1300))

    def test_allocate_exact(self):
        for disc in (1, 100, 101, 999, 1000):
            sh = inv._allocate(disc, [333, 333, 334])
            self.assertEqual(sum(sh), disc)
            self.assertTrue(all(0 <= s <= t for s, t in zip(sh, [333, 333, 334])))
        self.assertEqual(inv._allocate(0, [5, 5]), [0, 0])

    def test_validation_and_atomicity(self):
        c = self.c
        bad = [dict(items=[]), dict(discount="999"), dict(paid="999"), dict(items=[(self.sugar, "0", "5")]),
               dict(items=[(self.sugar, "1", "-5")]), dict(items=[(9999, "1", "5")]), dict(date=day(-2))]
        for kw in bad:
            with self.assertRaises(ValidationError, msg=str(kw)):
                self.make(**kw)
        with self.assertRaises(ValidationError):
            inv.create_invoice(c, "purchase", 9999, 1, [(self.sugar, "1", "5")])
        with self.assertRaises(ValidationError):
            inv.create_invoice(c, "purchase", self.sup, 9999, [(self.sugar, "1", "5")])
        # فشل في آخر خطوة (فترة الخزينة مقفولة والفاتورة فيها دفعة) => مفيش أي أثر
        tr.close_day(c, day(1))
        with self.assertRaises(ValidationError):
            self.make(paid="50", date=day(2))
        self.assertEqual(c.execute("SELECT COUNT(*) FROM invoices").fetchone()[0], 0)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM invoice_items").fetchone()[0], 0)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM stock_movements WHERE ref_type='invoice'").fetchone()[0], 0)
        self.assertEqual(self.sup_bal(), 10000)
        self.assertEqual(self.bal(self.sugar), 10000)
        self.assertEqual(products.get(c, self.sugar)["avg_cost_c"], 1000)
        self.make(paid="0", date=day(2))                              # من غير دفعة مفيش مشكلة
        self.make(paid="50", date=day(0))

    def test_backdated_movement_date(self):
        iid = self.make(date=day(3))
        m = self.c.execute("SELECT created_at FROM stock_movements WHERE ref_id=?", (iid,)).fetchone()[0]
        self.assertTrue(m.startswith(day(3)))

    def test_update(self):
        iid = self.make(paid="50")                                    # 10 @ 20 = 200، مدفوع 50
        inv.update_invoice(self.c, iid, self.sup, 1, [(self.sugar, "12", "20"), (self.tea, "4", "5")], "10", "100")
        h = inv.get_invoice(self.c, iid)
        self.assertEqual((h["invoice"]["total_c"], h["invoice"]["paid_c"], len(h["items"])), (25000, 10000, 2))
        self.assertEqual(h["invoice"]["number"], 1)
        self.assertEqual(self.bal(self.sugar), 10000 + 12000)          # الأثر القديم اتعكس والجديد اتطبّق
        self.assertEqual(self.bal(self.tea), 4000)
        self.assertEqual(self.sup_bal(), 10000 + 25000 - 10000)
        live = self.c.execute("SELECT COUNT(*) FROM treasury_entries WHERE voided=0").fetchone()[0]
        self.assertEqual(live, 1)                                      # دفعة قديمة اتلغت وجديدة اتسجلت
        self.assertEqual(tr.balance(self.c), -10000)
        # تغيير المورد والمخزن
        sup2 = parties.create(self.c, "supplier", "مورد 2")
        from hesabat.logic import warehouses
        w2 = warehouses.create(self.c, "فرع")
        inv.update_invoice(self.c, iid, sup2, w2, [(self.sugar, "12", "20")], "0", "0")
        self.assertEqual(self.bal(self.sugar, 1), 10000)
        self.assertEqual(self.bal(self.sugar, w2), 12000)
        self.assertEqual(self.sup_bal(), 10000)                        # المورد القديم رجع لرصيده الافتتاحي
        self.assertEqual({r["id"]: r["balance_c"] for r in parties.list_parties(self.c, "supplier")}[sup2], 24000)
        self.assertEqual(self.bal(self.tea), 0)

    def test_update_respects_sold_stock(self):
        iid = self.make()                                              # 10 جداد => الرصيد 20
        inventory.record_sale(self.c, self.sugar, 1, "18")             # الرصيد 2
        with self.assertRaises(ValidationError):                       # تقليل لـ 5: هيحتاج يسحب 5 ومعاه 2
            inv.update_invoice(self.c, iid, self.sup, 1, [(self.sugar, "5", "20")])
        self.assertEqual(inv.get_invoice(self.c, iid)["invoice"]["total_c"], 20000)     # اتراجع كله
        self.assertEqual(self.bal(self.sugar), 2000)
        inv.update_invoice(self.c, iid, self.sup, 1, [(self.sugar, "12", "20")])        # زيادة تمام
        self.assertEqual(self.bal(self.sugar), 4000)

    def test_cancel(self):
        iid = self.make(paid="50")
        inv.cancel_invoice(self.c, iid)
        self.assertEqual(self.bal(self.sugar), 10000)
        self.assertEqual(self.sup_bal(), 10000)
        self.assertEqual(tr.balance(self.c), 0)
        self.assertEqual(inv.get_invoice(self.c, iid)["invoice"]["status"], "cancelled")
        self.assertEqual(products.get(self.c, self.sugar)["avg_cost_c"], 1000)         # المتوسط رجع
        for fn in (lambda: inv.cancel_invoice(self.c, iid),
                   lambda: inv.update_invoice(self.c, iid, self.sup, 1, [(self.sugar, "1", "1")])):
            with self.assertRaises(ValidationError):
                fn()
        # سجل المورد محتفظ بالتاريخ (فاتورة + دفعة + عكسهم)
        st = parties.statement(self.c, "supplier", self.sup)
        self.assertEqual(st["balance_c"], 10000)
        self.assertGreaterEqual(len(st["rows"]), 4)

    def test_cancel_blocked_if_sold(self):
        iid = self.make()
        inventory.record_sale(self.c, self.sugar, 1, "15")             # باقي 5 من 20
        with self.assertRaises(ValidationError) as cm:
            inv.cancel_invoice(self.c, iid)
        self.assertIn("اتباع", str(cm.exception))
        self.assertEqual(inv.get_invoice(self.c, iid)["invoice"]["status"], "active")
        self.assertEqual(self.bal(self.sugar), 5000)

    def test_average_cost_restored_after_cancel_of_second_purchase(self):
        self.make()                                                    # 10 @ 20 => المتوسط 15
        i2 = self.make(items=[(self.sugar, "10", "40")])               # المتوسط (20*15 + 10*40)/30 = 23.33
        self.assertEqual(products.get(self.c, self.sugar)["avg_cost_c"], 2333)
        inv.cancel_invoice(self.c, i2)
        self.assertEqual(products.get(self.c, self.sugar)["avg_cost_c"], 1500)

    def test_old_sale_profit_unchanged_by_invoice_edit(self):
        i1 = self.make(items=[(self.sugar, "10", "20")])               # المتوسط 15
        inventory.record_sale(self.c, self.sugar, 1, "4", "18")        # تكلفة 15
        self.make(items=[(self.sugar, "10", "50")])                    # المتوسط يتغير
        from hesabat.logic import reports
        self.assertEqual(reports.dashboard(self.c)["tp"], 4 * (1800 - 1500))


class PurchaseReturnTests(InvoiceBase):
    def test_return_effects_and_cancel(self):
        self.make(paid="0")                                            # الرصيد 20، المورد 100 + 200 = 300
        rid = self.make(items=[(self.sugar, "5", "20")], kind="purchase_return", paid="30")   # مرتجع 100، استلمنا 30
        self.assertEqual(self.bal(self.sugar), 15000)
        self.assertEqual(self.sup_bal(), 10000 + 20000 - 10000 + 3000)   # 100+200-100+30
        self.assertEqual(tr.balance(self.c), 3000)                     # قبضنا من المورد
        h = inv.get_invoice(self.c, rid)["invoice"]
        self.assertEqual((h["kind"], h["number"]), ("purchase_return", 1))
        self.assertEqual(products.get(self.c, self.sugar)["avg_cost_c"], 1500)          # المرتجع مبيغيّرش المتوسط
        inv.cancel_invoice(self.c, rid)
        self.assertEqual(self.bal(self.sugar), 20000)
        self.assertEqual(self.sup_bal(), 30000)
        self.assertEqual(tr.balance(self.c), 0)

    def test_cannot_return_more_than_stock(self):
        with self.assertRaises(ValidationError) as cm:
            self.make(items=[(self.sugar, "11", "10")], kind="purchase_return")
        self.assertIn("المتاح", str(cm.exception))
        with self.assertRaises(ValidationError):                       # سطرين لنفس الصنف مجموعهم أكبر من المتاح
            self.make(items=[(self.sugar, "6", "10"), (self.sugar, "6", "10")], kind="purchase_return")
        self.assertEqual(self.bal(self.sugar), 10000)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM invoices").fetchone()[0], 0)

    def test_update_return(self):
        rid = self.make(items=[(self.sugar, "8", "10")], kind="purchase_return")      # الرصيد 2
        inv.update_invoice(self.c, rid, self.sup, 1, [(self.sugar, "9", "10")])        # الفرق 1 بس والمتاح 2
        self.assertEqual(self.bal(self.sugar), 1000)
        with self.assertRaises(ValidationError):
            inv.update_invoice(self.c, rid, self.sup, 1, [(self.sugar, "11", "10")])   # كمية أكبر من اللي كان في المخزن
        self.assertEqual(self.bal(self.sugar), 1000)


class PreviewTests(unittest.TestCase):
    def test_preview(self):
        p = inv.preview([(1, "2.5", "10"), (2, "1", "0.99")], "1", "5")
        self.assertEqual(p["line_totals"], [2500, 99])
        self.assertEqual((p["subtotal_c"], p["total_c"], p["remaining_c"]), (2599, 2499, 1999))
        with self.assertRaises(ValidationError):
            inv.preview([])
        with self.assertRaises(ValidationError):
            inv.preview([(1, "x", "1")])


if __name__ == "__main__":
    unittest.main(verbosity=2)
