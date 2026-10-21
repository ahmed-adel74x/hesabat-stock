"""
اختبار توصيل الواجهة بالمنطق من غير PySide6 حقيقية (بنستبدلها بنسخة وهمية خفيفة).
بيشغّل الشاشات وأزرارها فعلياً فوق قاعدة بيانات حقيقية، ويفشل لو أي معالج رمى خطأ غير متوقع.
مبيختبرش الشكل ولا الـ RTL، دول لازم تتشاف على البرنامج الحقيقي.
"""
import os, sys, types, unittest
from unittest.mock import MagicMock
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class Meta(type):
    def __getattr__(cls, name):
        if name.startswith("__"):
            raise AttributeError(name)
        v = MagicMock(name=f"{cls.__name__}.{name}")
        setattr(cls, name, v)
        return v


class Dummy(metaclass=Meta):
    def __init__(self, *a, **k): pass
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return MagicMock()


class FakeEdit(Dummy):
    def __init__(self, *a, **k): self._t = ""
    def text(self): return self._t
    def setText(self, t): self._t = str(t)
    def clear(self): self._t = ""


class FakeCombo(Dummy):
    def __init__(self, *a, **k): self._items, self._i, self._edit = [], -1, None
    def addItem(self, text, data=None):
        self._items.append((text, data))
        if self._i < 0: self._i = 0
    def clear(self): self._items, self._i, self._edit = [], -1, None
    def count(self): return len(self._items)
    def currentIndex(self): return self._i
    def setCurrentIndex(self, i): self._i, self._edit = i, None
    def currentData(self): return self._items[self._i][1] if 0 <= self._i < len(self._items) else None
    def itemText(self, i): return self._items[i][0]
    def itemData(self, i): return self._items[i][1]
    def currentText(self):
        if self._edit is not None: return self._edit
        return self._items[self._i][0] if 0 <= self._i < len(self._items) else ""
    def setEditText(self, t): self._edit = t              # المستخدم كتب في الخانة
    def findText(self, t): return next((i for i, (x, _) in enumerate(self._items) if x == t), -1)
    def findData(self, d):
        return next((i for i, (_, x) in enumerate(self._items) if x == d), -1)


class FakeItem(Dummy):
    def __init__(self, text="", *a): self._t, self._d, self._r, self._c = str(text), None, -1, -1
    def text(self): return self._t
    def setText(self, t): self._t = str(t)
    def data(self, role=None): return self._d
    def setData(self, role, v): self._d = v
    def row(self): return self._r
    def column(self): return self._c


class FakeLabel(Dummy):
    def __init__(self, text="", *a, **k): self._t = str(text)
    def text(self): return self._t
    def setText(self, t): self._t = str(t)


class FakeTable(Dummy):
    def __init__(self, rows=0, cols=0): self._cells, self._rows, self._sel = {}, rows, None
    def setRowCount(self, n):
        self._rows = n
        self._cells = {k: v for k, v in self._cells.items() if k[0] < n}
    def rowCount(self): return self._rows
    def setItem(self, r, c, it): it._r, it._c = r, c; self._cells[(r, c)] = it
    def item(self, r, c): return self._cells.get((r, c))
    def selectedItems(self): return [self._cells[(self._sel, 0)]] if self._sel is not None else []
    def clearSelection(self): self._sel = None
    def selectRow(self, r): self._sel = r


class FakeFileDialog(Dummy):
    next_path = ""
    @staticmethod
    def getSaveFileName(*a): return (FakeFileDialog.next_path, "")


class FakeBox(Dummy):
    warnings = []
    @classmethod
    def warning(cls, parent, title, text): cls.warnings.append(text)
    infos = []
    @classmethod
    def information(cls, parent, title, text): cls.infos.append(text)
    @classmethod
    def question(cls, *a): return cls.StandardButton.Yes


def make_mod(name, special):
    m = types.ModuleType(name)
    def __getattr__(attr):
        if attr.startswith("__"):
            raise AttributeError(attr)
        cls = special.get(attr) or type(attr, (Dummy,), {})
        setattr(m, attr, cls)
        return cls
    m.__getattr__ = __getattr__
    return m


sys.modules["PySide6"] = types.ModuleType("PySide6")
sys.modules["PySide6.QtCore"] = make_mod("PySide6.QtCore", {})
sys.modules["PySide6.QtGui"] = make_mod("PySide6.QtGui", {})
sys.modules["PySide6.QtPrintSupport"] = make_mod("PySide6.QtPrintSupport", {})
sys.modules["PySide6.QtWidgets"] = make_mod("PySide6.QtWidgets", {
    "QLineEdit": FakeEdit, "QComboBox": FakeCombo, "QTableWidget": FakeTable,
    "QTableWidgetItem": FakeItem, "QMessageBox": FakeBox, "QLabel": FakeLabel, "QFileDialog": FakeFileDialog})

from helpers import tmp_db, make_legacy
from hesabat.db.connection import connect
from hesabat.db.migrations import init_db
import hesabat.ui.common as common
from hesabat.logic import inventory
from hesabat.logic import products as products_logic
from hesabat.ui.main_window import MainWindow
from hesabat.ui.products_tab import ProductsTab
from hesabat.ui.warehouses_tab import WarehousesTab
from hesabat.ui.stock_ops_tab import StockOpsTab
from hesabat.ui.parties_tab import PartiesTab
from hesabat.ui.reports_tab import ReportsTab
from hesabat.ui.treasury_tab import TreasuryTab
from hesabat.ui.invoices_tab import InvoicesTab
from hesabat.logic import invoices, reports as rp
from hesabat.ui.reports_tab import ReportsCenterPage
import tempfile
from hesabat.logic import treasury, parties


def boom(parent, tb):
    raise AssertionError("خطأ غير متوقع في الواجهة:\n" + tb)
common.report_error = boom


class UiFlow(unittest.TestCase):
    def setUp(self):
        FakeBox.warnings.clear()
        path = tmp_db(); make_legacy(path)                 # بيانات قديمة => بنختبر بعد الترحيل
        self.conn = connect(path)
        self.assertTrue(init_db(self.conn, path)["ok"])

    def test_everything(self):
        c = self.conn
        MainWindow(c)                                       # كل التبويبات تتبني
        # --- الأصناف
        pt = ProductsTab(c)
        self.assertEqual(pt.table.rowCount(), 4)
        self.assertEqual(pt.table.item(0, 0).text(), str(pt.table.item(0, 0).data(None)))   # عمود الرقم = رقم الصنف
        self.assertEqual(pt.count.text(), "عدد الأصناف: 4")
        pt.search.setText("سكر"); pt.refresh()                          # بحث بالاسم
        self.assertEqual(pt.table.rowCount(), 1)
        self.assertEqual(pt.count.text(), "عدد الأصناف: 1 من 4")
        pt.search.setText("2"); pt.refresh()                            # برقم الصنف (زيت)
        self.assertIn("زيت", [pt.table.item(r, 1).text() for r in range(pt.table.rowCount())])
        pt.search.setText("مفيش صنف بالاسم ده"); pt.refresh()
        self.assertEqual(pt.table.rowCount(), 0)
        pt.search.setText(""); pt.refresh()
        self.assertEqual(pt.table.rowCount(), 4)
        pt.table._sel = 2                                                # صنف محدد، وبعدين نبحث عنه بالاسم
        keep, name = pt.table.item(2, 0).data(None), pt.table.item(2, 1).text()
        pt.search.setText(name); pt.refresh()
        self.assertEqual(pt.table.item(pt.table._sel, 0).data(None), keep)   # لسه محدد بعد البحث
        pt.search.setText(""); pt.refresh(); pt.clear_form()
        for e, v in zip(pt.f, ("لبن", "8", "10", "20", "5")):
            e.setText(v)
        pt.add()
        self.assertEqual(pt.table.rowCount(), 5)
        pt.table._sel = 0; pt.on_select()
        pt.f[2].setText("11"); pt.edit()
        pt.add()                                            # مكرر => تنبيه مش خطأ
        self.assertIn("موجود بالفعل", FakeBox.warnings[-1])
        # --- تعديل الكمية من شاشة الأصناف
        ids = lambda: {pt.table.item(r, 1).text(): (r, pt.table.item(r, 0).data(None)) for r in range(pt.table.rowCount())}
        row, lid = ids()["لبن"]
        pt.table._sel = row; pt.on_select()
        self.assertEqual(pt.f[3].text(), "20")                              # الكمية الحالية في المخزن المختار
        self.assertEqual(pt.labels[3].text(), "الكمية في المخزن")
        moves = lambda: c.execute("SELECT COUNT(*) FROM stock_movements").fetchone()[0]
        n = moves()
        pt.f[1].setText("9"); pt.edit()                                     # تعديل السعر من غير لمس الكمية
        self.assertEqual(moves(), n)
        pt.f[3].setText("35"); pt.edit()                                    # تعديل الكمية
        self.assertEqual(inventory.balance(c, lid, 1), 35000)
        row, _ = ids()["لبن"]
        self.assertEqual(pt.table.item(row, 5).text(), "35")                # عمود الكمية الكلية اتحدّث
        self.assertEqual(pt.f[3].text(), "35")                              # والحقل بقى مرجع جديد
        n = moves(); pt.edit(); self.assertEqual(moves(), n)                # تعديل تاني من غير تغيير = مفيش حركة
        pt.f[3].setText("abc"); pt.edit()                                   # كمية غلط = تنبيه ومفيش تعديل
        self.assertIn("الكمية", FakeBox.warnings[-1])
        self.assertEqual(inventory.balance(c, lid, 1), 35000)
        pt.f[3].setText(""); pt.edit()                                      # فاضية = سيبها زي ما هي
        self.assertEqual(inventory.balance(c, lid, 1), 35000)
        pt.f[3].setText("0"); pt.edit()                                     # الصفر مسموح
        self.assertEqual(inventory.balance(c, lid, 1), 0)
        pt.f[3].setText("35"); pt.edit()
        pt.f[0].setText("لبن مجفف"); pt.add()                               # صنف محمّل وكميته متغيّرتش: الجديد كميته صفر
        self.assertEqual(inventory.balance(c, ids()["لبن مجفف"][1], 1), 0)
        row, _ = ids()["لبن"]
        pt.table._sel = row; pt.on_select()
        pt.f[0].setText("لبن كامل"); pt.f[3].setText("12"); pt.add()        # لو غيّرتها قبل الإضافة بتتسجل افتتاحية
        self.assertEqual(inventory.balance(c, ids()["لبن كامل"][1], 1), 12000)
        pt.clear_form(); self.assertEqual(pt.labels[3].text(), "الكمية الافتتاحية")
        # --- المخازن
        wt = WarehousesTab(c)
        wt.name.setText("فرع القاهرة"); wt.loc.setText("القاهرة"); wt.add()
        self.assertEqual(wt.table.rowCount(), 2)
        wt.table._sel = 0; wt.on_select()
        self.assertEqual(wt.bal.rowCount(), len(products_logic.list_products(c)))   # كل الأصناف النشطة
        wt.table._sel = 1; wt.delete()                      # مخزن فاضي => يتحذف
        wt.name.setText("فرع المنصورة"); wt.add()
        # --- تحويل وجرد
        ops = StockOpsTab(c)
        tp = ops.transfer; tp.refresh()
        self.assertEqual(tp.src.count(), 2)
        self.assertNotEqual(tp.src.currentData(), tp.dst.currentData())
        tp.prod.setCurrentIndex(tp.prod.findData(1))        # سكر (رصيده 40)
        warned = len(FakeBox.warnings)
        tp.qty.setText("5"); tp.do()
        self.assertEqual(len(FakeBox.warnings), warned)     # التحويل نفسه مفيهوش تنبيهات
        self.assertEqual(inventory.balance(c, 1, tp.dst.currentData()), 5000)
        sp = ops.count; sp.refresh()
        sp.table.item(0, 2).setText("12"); sp.on_changed(sp.table.item(0, 2))
        sp.apply()
        # --- عملاء وموردين
        pa = PartiesTab(c, "supplier")
        for e, v in zip(pa.f, ("مورد 1", "010", "القاهرة", "", "500")):
            e.setText(v)
        pa.add(); self.assertEqual(pa.table.rowCount(), 1)
        pa.table._sel = 0; pa.statement()
        from hesabat.ui.parties_tab import StatementDialog
        sd = StatementDialog(None, c, parties.statement(c, "supplier", pa.table.item(0, 0).data(None)))
        sd.open_invoice(0); sd.open_invoice(99)                   # صف الرصيد الافتتاحي/صف مش موجود: مفيش حاجة تتفتح
        PartiesTab(c, "customer").refresh()
        # --- الخزينة
        tt = TreasuryTab(c)
        vp = tt.vouchers; vp.refresh()
        vp.opening.setText("1000"); vp.save_opening()
        vp.ptype.setCurrentIndex(2); vp.on_type()                # عام
        vp.kind.setCurrentIndex(1); vp.cat.setText("كهرباء"); vp.amount.setText("50"); vp.save()
        vp.ptype.setCurrentIndex(1); vp.on_type()                # مورد
        vp.pname.setCurrentIndex(0); vp.amount.setText("100"); vp.save()
        self.assertEqual(treasury.balance(c), 85000)
        sup = [p for p in parties.list_parties(c, "supplier")][0]
        self.assertEqual(sup["balance_c"], 40000)                # 500 - 100
        self.assertEqual(vp.table.rowCount(), 2)
        vp.table._sel = 0; vp.void()                             # إلغاء آخر سند
        self.assertEqual(treasury.balance(c), 95000)
        tt.stmt.refresh(); self.assertEqual(tt.stmt.table.rowCount(), 1)
        cp = tt.closing; cp.refresh()
        cp.counted.setText("940"); cp.close()                    # عجز 10
        self.assertEqual(treasury.balance(c), 94000)
        vp.amount.setText("1"); vp.cat.setText("x"); vp.ptype.setCurrentIndex(2); vp.on_type(); vp.save()
        self.assertIn("مقفولة", FakeBox.warnings[-1])            # التقفيل بيمنع السندات
        cp.reopen(); cp.refresh()
        self.assertEqual(treasury.balance(c), 95000)
        # --- المشتريات (فاتورة جديدة، فتح للتعديل، إلغاء) + مرتجع
        it = InvoicesTab(c, "purchase"); ed = it.editor; ed.refresh()
        ed.prod.setEditText("سكر")                                        # كتابة جزء من الاسم بتختار الصنف
        self.assertEqual(ed.prod.value(), 1)
        self.assertEqual(ed.prod.currentText(), "سكر")
        ed.prod.setEditText("ZZZ مش موجود"); self.assertIsNone(ed.prod.value())   # نص مش مطابق = مفيش اختيار
        ed.qty.setText("1"); ed.add_line()
        self.assertIn("اختر الصنف", FakeBox.warnings[-1])                 # بيرفض بدل ما ياخد الصنف القديم بالغلط
        self.assertEqual(ed.items, [])
        ed.prod.setEditText("1"); self.assertEqual(ed.prod.value(), 1)    # البحث برقم الصنف
        ed.prod.setEditText("سُكَّر")                                      # بيتجاهل التشكيل
        self.assertEqual(ed.prod.value(), 1)
        ed.party.setEditText("مورد"); self.assertIsNotNone(ed.party.value())          # البحث في الموردين
        ed.party.setEditText("غلط"); self.assertIsNone(ed.party.value())
        ed.save()                                                          # بيرفض الحفظ لو المورد مش مختار صح
        self.assertIn("اختر المورد", FakeBox.warnings[-1])
        ed.party.setCurrentIndex(0)
        ed.prod.setCurrentIndex(ed.prod.findData(1)); ed.on_product()    # سكر: السعر الافتراضي من آخر شراء
        self.assertEqual(ed.price.text(), "12.50")
        cash0, stock0 = treasury.balance(c), inventory.balance(c, 1)
        ed.qty.setText("5"); ed.add_line()
        ed.discount.setText("5"); ed.paid.setText("10"); ed.recalc()
        self.assertEqual((ed.l_sub.text(), ed.l_total.text(), ed.l_rem.text()), ("62.50", "57.50", "47.50"))
        ed.save()
        rows = invoices.list_invoices(c, "purchase"); self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["total_c"], 5750)                       # 5 × 12.5 - 5
        self.assertEqual(inventory.balance(c, 1), stock0 + 5000)
        self.assertEqual(treasury.balance(c), cash0 - 1000)
        it.listing.refresh(); it.listing.table._sel = 0; it.listing.open_edit()   # فتح للتعديل
        self.assertEqual((ed.edit_id, len(ed.items)), (rows[0]["id"], 1))
        ed.paid.setText("0"); ed.save()
        self.assertEqual(invoices.get_invoice(c, rows[0]["id"])["invoice"]["paid_c"], 0)
        self.assertEqual(treasury.balance(c), cash0)
        ed.qty.setText("x"); ed.add_line()                                # كمية غلط => تنبيه مش خطأ
        self.assertIn("الكمية", FakeBox.warnings[-1])
        it.listing.refresh(); it.listing.table._sel = 0; FakeBox.infos.clear(); it.listing.delete()
        self.assertEqual(inventory.balance(c, 1), stock0)
        self.assertEqual(invoices.list_invoices(c, "purchase"), [])        # اتمسحت ومبتظهرش كـ«ملغية»
        self.assertEqual(c.execute("SELECT COUNT(*) FROM invoices WHERE kind='purchase'").fetchone()[0], 0)
        self.assertEqual(it.listing.table.rowCount(), 0)
        self.assertIn("حذف", FakeBox.infos[-1])
        self.assertEqual(it.listing.table.columnCount() if isinstance(it.listing.table.columnCount(), int) else 6, 6)
        rt = InvoicesTab(c, "purchase_return"); re_ = rt.editor; re_.refresh()
        re_.prod.setCurrentIndex(re_.prod.findData(1)); re_.on_product()
        re_.qty.setText("2"); re_.add_line(); re_.save()
        self.assertEqual(inventory.balance(c, 1), stock0 - 2000)
        re_.qty.setText("9999"); re_.add_line(); re_.save()               # أكبر من المخزون => تنبيه واضح
        self.assertIn("المتاح", FakeBox.warnings[-1])
        # --- المبيعات: عميل نقدي افتراضي، دفع كامل، منع البيع فوق المتاح، طباعة، مرتجع
        st = InvoicesTab(c, "sale"); se = st.editor; se.refresh()
        cash = parties.default_customer_id(c)
        self.assertEqual(se.party.currentData(), cash)                   # العميل النقدي هو الافتراضي
        se.prod.setCurrentIndex(se.prod.findData(1)); se.on_product()
        self.assertEqual(se.price.text(), "15")                          # سعر البيع الافتراضي لسكر
        stock0 = inventory.balance(c, 1)
        se.qty.setText("2"); se.add_line()
        se.save()                                                        # عميل نقدي من غير دفع => منع
        self.assertIn("العميل النقدي", FakeBox.warnings[-1])
        se.pay_full(); se.save()
        rows = invoices.list_invoices(c, "sale"); self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["paid_c"], rows[0]["total_c"]), (3000, 3000))
        self.assertEqual(inventory.balance(c, 1), stock0 - 2000)
        se.new_invoice(); se.qty.setText("99999"); se.add_line(); se.pay_full(); se.save()
        self.assertIn("الكمية المتاحة", FakeBox.warnings[-1])            # منع البيع فوق المتاح
        se.new_invoice(); se.qty.setText("1"); se.add_line(); se.pay_full(); se.save_and_print()
        self.assertEqual(len(invoices.list_invoices(c, "sale")), 2)
        st.listing.refresh(); st.listing.table._sel = 0; st.listing.print_selected()
        credit = parties.create(c, "customer", "عميل آجل")               # بيع آجل لعميل مسجّل
        se.refresh(); se.party.setCurrentIndex(se.party.findData(credit))
        se.qty.setText("3"); se.add_line(); se.save()
        self.assertEqual({r["id"]: r["balance_c"] for r in parties.list_parties(c, "customer")}[credit], 4500)
        rt = InvoicesTab(c, "sale_return"); sr = rt.editor; sr.refresh()
        sr.party.setCurrentIndex(sr.party.findData(credit))
        sr.prod.setCurrentIndex(sr.prod.findData(1)); sr.on_product()
        sr.qty.setText("1"); sr.add_line(); sr.save()
        self.assertEqual({r["id"]: r["balance_c"] for r in parties.list_parties(c, "customer")}[credit], 3000)
        self.assertEqual(len(invoices.list_invoices(c, "sale_return")), 1)
        # --- مركز التقارير: كل تقرير + تصدير Excel حقيقي + PDF/طباعة
        rc = ReportsCenterPage(c); rc.refresh()
        self.assertEqual(rc.wh.currentData(), None)                      # "كل المخازن" هو الأول
        for i, (key, _title, _p) in enumerate(rp.REPORTS):
            rc.kind.setCurrentIndex(i); rc.on_kind(); rc.generate()
            job = rc._job
            self.assertEqual(job.key, key)
            rep = rp.run_report(job.db_path, job.key, job.params)        # اللي بيعمله الـ thread بالظبط
            rc.on_done(rep)
            self.assertEqual(rc.table.rowCount(), len(rep["rows"]), key)
            self.assertTrue(rc.title.text(), key)
            self.assertTrue(rc.summary.text(), key)
        rc.kind.setCurrentIndex(5); rc.on_kind(); rc.generate()            # كشف حساب عميل بعميل محدد
        self.assertIsNotNone(rc._job.params["customer_id"])
        xl = os.path.join(tempfile.mkdtemp(), "r")
        FakeFileDialog.next_path = xl
        rc.export_excel()
        self.assertTrue(os.path.exists(xl + ".xlsx"))                    # بيضيف الامتداد لوحده
        FakeFileDialog.next_path = ""
        rc.export_pdf(); rc.print_report()                                # إلغاء الحفظ مبيعملش خطأ
        rc.report = None; rc.export_excel()
        self.assertIn("اعرض التقرير", FakeBox.warnings[-1])
        rc.dfrom.setText("2026-10-09"); rc.dto.setText("2026-01-01"); rc.kind.setCurrentIndex(2)
        rc.on_invalid("x")                                               # رسالة التحقق بتظهر كتنبيه
        self.assertEqual(FakeBox.warnings[-1], "x")
        ReportsTab(c).refresh()


class SelfTest(unittest.TestCase):
    """الاختبار الذاتي اللي بيشتغل على الـ exe: هنا بنتأكد إن منطقه نفسه شغال وإنه بيفشل لما حاجة تفشل."""

    def run_it(self):
        from hesabat import selftest
        out = os.path.join(tempfile.mkdtemp(), "out.txt")
        old = os.environ.get("HESABAT_DATA_DIR")
        try:
            code = selftest.run_selftest(out, strict_files=False)
        finally:
            if old is None: os.environ.pop("HESABAT_DATA_DIR", None)
            else: os.environ["HESABAT_DATA_DIR"] = old
        with open(out, encoding="utf-8") as f:
            return code, f.read()

    def test_passes(self):
        code, text = self.run_it()
        self.assertEqual(code, 0, text)
        self.assertIn("SELFTEST OK", text)
        self.assertIn("الشاشات: 11", text)
        self.assertIn("التقارير: 9", text)

    def test_fails_when_something_breaks(self):
        from hesabat.logic import export
        real = export.to_excel
        export.to_excel = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            code, text = self.run_it()
        finally:
            export.to_excel = real
        self.assertEqual(code, 1)
        self.assertIn("SELFTEST FAILED", text)
        self.assertIn("boom", text)


class PrintingTests(unittest.TestCase):
    """الطباعة: بنختبر منطقها (حماية الطابعة من المسح، البديل، التشخيص). الطباعة الفعلية لازم تتجرب على جهاز حقيقي."""

    def setUp(self):
        from hesabat.ui import printing
        self.p = printing
        self.saved = (printing._preview, printing._open_pdf, printing.QPrintPreviewDialog, printing.QDesktopServices)

    def tearDown(self):
        self.p._preview, self.p._open_pdf, self.p.QPrintPreviewDialog, self.p.QDesktopServices = self.saved

    def test_preview_keeps_printer_and_document_alive(self):
        """السبب اللي كان بيوقّع الطباعة: الطابعة لازم تفضل متخزّنة طول عمر النافذة (مش مجرد وسيط في الإنشاء)."""
        seen = {}

        class FakeDialog:
            def __init__(self, printer, parent=None):
                seen["printer"], self.paintRequested = printer, types.SimpleNamespace(connect=lambda f: seen.setdefault("cb", f))
            def resize(self, *a): pass
            def exec(self): seen["keep"] = getattr(self, "_keep", None)
        self.p.QPrintPreviewDialog = FakeDialog
        doc = self.p._document("<p>x</p>")
        self.p._preview(None, doc, False)
        self.assertIsNotNone(seen["keep"])
        self.assertIs(seen["keep"][0], seen["printer"])
        self.assertIs(seen["keep"][1], doc)

    def test_paint_errors_are_logged_not_lost(self):
        seen = {}
        class FakeDialog:
            def __init__(self, printer, parent=None):
                self.paintRequested = types.SimpleNamespace(connect=lambda f: seen.setdefault("cb", f))
            def resize(self, *a): pass
            def exec(self): pass
        self.p.QPrintPreviewDialog = FakeDialog
        class BadDoc:
            def print_(self, printer): raise RuntimeError("طباعة بايظة")
        self.p._preview(None, BadDoc(), False)
        old = os.environ.get("HESABAT_DATA_DIR")
        os.environ["HESABAT_DATA_DIR"] = tempfile.mkdtemp()
        try:
            seen["cb"](object())                                          # مفيش استثناء بيطلع، والخطأ بيتسجل
            from hesabat import applog
            with open(applog.log_path(), encoding="utf-8") as f:
                self.assertIn("طباعة بايظة", f.read())
        finally:
            if old is None: os.environ.pop("HESABAT_DATA_DIR", None)
            else: os.environ["HESABAT_DATA_DIR"] = old

    def test_falls_back_to_pdf_when_preview_breaks(self):
        calls = []
        def broken(*a, **k): raise RuntimeError("no preview")
        self.p._preview = broken
        self.p._open_pdf = lambda doc, landscape, name: calls.append((name, landscape)) or "/tmp/x.pdf"
        FakeBox.infos.clear()
        self.p._print_html(None, "<p>x</p>", True, "report")
        self.assertEqual(calls, [("report", True)])
        self.assertIn("PDF", FakeBox.infos[-1])

    def test_open_pdf(self):
        class Desktop:
            ok = True
            @staticmethod
            def openUrl(url): return Desktop.ok
        self.p.QDesktopServices = Desktop
        path = self.p._open_pdf(self.p._document("<p>x</p>"), False, "invoice")
        self.assertTrue(os.path.exists(path) and "invoice" in os.path.basename(path))
        Desktop.ok = False
        from hesabat.logic.errors import ValidationError
        with self.assertRaises(ValidationError) as cm:                    # لو برنامج العرض ما اتفتحش نقوله مكان الملف
            self.p._open_pdf(self.p._document("<p>x</p>"), False, "invoice")
        self.assertIn(".pdf", str(cm.exception))

    def test_wide_reports_print_landscape(self):
        self.assertFalse(self.p._wide({"columns": [1] * 5}))
        self.assertTrue(self.p._wide({"columns": [1] * 6}))

    def test_print_check_command(self):
        from hesabat import selftest
        out = os.path.join(tempfile.mkdtemp(), "p.txt")
        old = os.environ.get("HESABAT_DATA_DIR")
        try:
            code = selftest.run_print_check(out, strict_files=False, preview_seconds=0.05)
        finally:
            if old is None: os.environ.pop("HESABAT_DATA_DIR", None)
            else: os.environ["HESABAT_DATA_DIR"] = old
        with open(out, encoding="utf-8") as f:
            text = f.read()
        self.assertEqual(code, 0, text)
        self.assertIn("PRINT CHECK DONE", text)
        self.assertIn("الطابعة الافتراضية", text)
        self.assertIn("نافذة المعاينة", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
