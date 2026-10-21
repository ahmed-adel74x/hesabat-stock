from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QTabWidget, QTextBrowser, QVBoxLayout, QWidget)

from ..logic import invoices, parties, products, treasury, warehouses
from ..logic.errors import ValidationError
from ..logic.money import fmt_money, plain_money, plain_qty
from .common import (button, card, cell, confirm, fill_combo, field_label, guard, make_table, safe_call,
                     selected_id)
from .printing import open_invoice_pdf, print_invoice
from .search_combo import SearchCombo



DELETE_WARNING = ("حذف الفاتورة نهائياً؟\nهيتعكس أثرها على المخزون وحساب الطرف والخزينة، وهتختفي من كل "
                  "الشاشات والتقارير وكشوف الحساب، ومش هتقدر ترجعها.")


class InvoiceViewDialog(QDialog):
    """عرض فاتورة كاملة بتفاصيلها (للقراءة بس)، مع زر طباعة."""

    def __init__(self, parent, conn, invoice_id, allow_change=False):
        super().__init__(parent)
        self.conn, self.invoice_id = conn, invoice_id
        self.action = None            # "edit" أو "deleted" لو المستخدم عدّل/مسح من هنا (الشاشة اللي فتحتها بتتصرف)
        self.setWindowTitle("تفاصيل الفاتورة")
        self.resize(640, 560)
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 16, 16, 16)
        view = QTextBrowser()
        view.setStyleSheet("background:#ffffff;color:#0f172a;")      # الفاتورة بتفضل زي الورقة حتى في الدارك
        view.document().setDefaultStyleSheet("body{color:#0f172a;}")
        view.setHtml(invoices.invoice_html(conn, invoice_id))
        v.addWidget(view, 1)
        row = QHBoxLayout()
        row.addWidget(button("طباعة", "success", self.print))
        if allow_change:
            row.addWidget(button("تعديل الفاتورة", "primary", self.edit))
            row.addWidget(button("مسح الفاتورة", "danger", self.delete))
        row.addStretch(1)
        row.addWidget(button("إغلاق", "primary", self.accept))
        v.addLayout(row)

    @guard
    def print(self):
        print_invoice(self, self.conn, self.invoice_id)

    @guard
    def edit(self):
        self.action = "edit"
        self.accept()

    @guard
    def delete(self):
        if confirm(self, DELETE_WARNING):
            invoices.delete_invoice(self.conn, self.invoice_id)
            self.action = "deleted"
            QMessageBox.information(self, "تم", "تم مسح الفاتورة ✔")
            self.accept()


class InvoicePage(QWidget):
    """شاشة إنشاء/تعديل فاتورة. الحسابات كلها من invoices.preview، والواجهة بتعرض بس."""

    def __init__(self, conn, kind):
        super().__init__()
        self.conn, self.kind, self.info = conn, kind, invoices.KINDS[kind]
        self.items = []          # [(product_id, الاسم, نص الكمية, نص السعر)]
        self.edit_id = None
        self._pending_default = False   # اختيار العميل النقدي تلقائياً في فاتورة جديدة
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 12, 18, 12)
        v.setSpacing(10)
        self.title = QLabel()
        self.title.setStyleSheet("font-size:18px;font-weight:bold")
        v.addWidget(self.title)

        head = card()
        g = QGridLayout(head)
        g.setContentsMargins(16, 12, 16, 12)
        g.setHorizontalSpacing(12)
        self.party, self.wh = SearchCombo(placeholder="اكتب اسم " + self.info["party_label"]), QComboBox()
        self.date, self.note = QLineEdit(), QLineEdit()
        for i, (t, w) in enumerate(((self.info["party_label"], self.party), ("المخزن", self.wh),
                                    ("التاريخ", self.date), ("ملاحظة", self.note))):
            g.addWidget(field_label(t), 0, i)
            g.addWidget(w, 1, i)
        g.setColumnStretch(3, 2)
        v.addWidget(head)

        add = card()
        a = QHBoxLayout(add)
        a.setContentsMargins(16, 10, 16, 10)
        self.prod = SearchCombo(by_number=True, placeholder="اكتب اسم الصنف أو رقمه")
        self.qty, self.price = QLineEdit(), QLineEdit()
        self.qty.setPlaceholderText("0")
        self.price.setPlaceholderText("0")
        a.addWidget(field_label("الصنف"))
        a.addWidget(self.prod, 3)
        a.addWidget(field_label("الكمية"))
        a.addWidget(self.qty, 1)
        a.addWidget(field_label("السعر"))
        a.addWidget(self.price, 1)
        a.addWidget(button("إضافة للفاتورة", "primary", self.add_line))
        v.addWidget(add)

        self.table = make_table(["الصنف", "الكمية", "السعر", "الإجمالي"])
        v.addWidget(self.table, 1)

        tot = card()
        t = QGridLayout(tot)
        t.setContentsMargins(16, 10, 16, 10)
        t.setHorizontalSpacing(12)
        self.discount, self.paid = QLineEdit(), QLineEdit()
        self.discount.setPlaceholderText("0")
        self.paid.setPlaceholderText("0")
        self.l_sub, self.l_total, self.l_rem = QLabel("0"), QLabel("0"), QLabel("0")
        for lab in (self.l_sub, self.l_total, self.l_rem):
            lab.setStyleSheet("font-size:16px;font-weight:bold")
        cells = (("الإجمالي الفرعي", self.l_sub), ("الخصم", self.discount), ("الإجمالي", self.l_total),
                 (self.info["cash_label"], self.paid), ("المتبقي", self.l_rem))
        for i, (txt, w) in enumerate(cells):
            t.addWidget(field_label(txt), 0, i)
            t.addWidget(w, 1, i)
        v.addWidget(tot)
        self.status = QLabel("")
        v.addWidget(self.status)

        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(button("حفظ", "success", self.save))
        row.addWidget(button("حفظ وطباعة", "success", self.save_and_print))
        row.addWidget(button("دفع كامل", "primary", self.pay_full))
        row.addWidget(button("فاتورة جديدة", "", self.new_invoice))
        row.addWidget(button("حذف السطر المحدد", "danger", self.remove_line))
        row.addStretch(1)
        v.addLayout(row)

        self.prod.currentIndexChanged.connect(self.on_product)
        self.discount.textChanged.connect(self.recalc)
        self.paid.textChanged.connect(self.recalc)
        self.new_invoice()

    def _say(self, text, ok=False):
        self.status.setText(text)
        self.status.setStyleSheet("color:%s;font-weight:bold" % ("#15803d" if ok else "#b91c1c"))

    @guard
    def refresh(self):
        fill_combo(self.party, parties.list_parties(self.conn, self.info["party"]))
        fill_combo(self.wh, warehouses.list_warehouses(self.conn))
        fill_combo(self.prod, products.list_products(self.conn))
        if self.edit_id is None and self._pending_default:
            self._select_default()
        if not self.price.text():
            self.on_product()

    def _select_default(self):
        """في فواتير العملاء: العميل النقدي هو الاختيار الافتراضي (للبيع السريع)."""
        if self.info["party"] != "customer":
            return
        i = self.party.findData(parties.default_customer_id(self.conn))
        if i >= 0:
            self.party.setCurrentIndex(i)
            self._pending_default = False

    @guard
    def on_product(self):
        pid = self.prod.currentData()
        if pid is not None:
            self.price.setText(plain_money(invoices.default_price(self.conn, self.kind, pid)))

    def recalc(self, *args):
        self._say("")
        if not self.items:
            self.table.setRowCount(0)
            for lab in (self.l_sub, self.l_total, self.l_rem):
                lab.setText(fmt_money(0))
            return
        triples = [(pid, q, p) for pid, _name, q, p in self.items]
        base = invoices.preview(triples)
        self.table.setRowCount(len(self.items))
        for r, ((_pid, name, q, p), lt) in enumerate(zip(self.items, base["line_totals"])):
            for c, val in enumerate((name, q, p, fmt_money(lt))):
                self.table.setItem(r, c, cell(val))
        self.l_sub.setText(fmt_money(base["subtotal_c"]))
        try:
            full = invoices.preview(triples, self.discount.text(), self.paid.text())
            self.l_total.setText(fmt_money(full["total_c"]))
            self.l_rem.setText(fmt_money(full["remaining_c"]))
        except ValidationError as e:
            self.l_total.setText(fmt_money(base["subtotal_c"]))
            self.l_rem.setText("-")
            self._say(str(e))

    @guard
    def add_line(self):
        pid = self.prod.value()
        if pid is None:
            raise ValidationError("اختر الصنف")
        qty, price = self.qty.text(), self.price.text()
        invoices.preview([(pid, qty, price)])        # بيتحقق من الكمية والسعر
        self.items.append((pid, self.prod.currentText(), qty.strip(), price.strip()))
        self.qty.clear()
        self.recalc()

    @guard
    def remove_line(self):
        sel = self.table.selectedItems()
        if not sel:
            raise ValidationError("اختر سطر من الجدول الأول")
        del self.items[sel[0].row()]
        self.recalc()

    @guard
    def new_invoice(self):
        self.items, self.edit_id = [], None
        self.title.setText(self.info["title"] + " - جديد")
        for e in (self.qty, self.note, self.discount, self.paid):
            e.clear()
        self.date.setText(treasury.today())
        self._pending_default = True
        self._select_default()
        self.recalc()

    @guard
    def pay_full(self):
        if not self.items:
            raise ValidationError("أضف أصناف للفاتورة الأول")
        p = invoices.preview([(pid, q, pr) for pid, _n, q, pr in self.items], self.discount.text())
        self.paid.setText(plain_money(p["total_c"]))

    def _save_invoice(self):
        party, wid = self.party.value(), self.wh.currentData()
        if party is None:
            raise ValidationError(f"اختر {self.info['party_label']} (أضفه الأول لو القائمة فاضية)")
        if wid is None:
            raise ValidationError("اختر المخزن")
        args = (party, wid, [(pid, q, p) for pid, _n, q, p in self.items], self.discount.text(), self.paid.text(),
                self.note.text(), self.date.text())
        if self.edit_id:
            iid = invoices.update_invoice(self.conn, self.edit_id, *args)
        else:
            iid = invoices.create_invoice(self.conn, self.kind, *args)
        number = invoices.get_invoice(self.conn, iid)["invoice"]["number"]
        self.new_invoice()
        self._say(f"✔ تم حفظ {self.info['title']} رقم {number}", ok=True)
        return iid

    @guard
    def save(self):
        self._save_invoice()

    @guard
    def save_and_print(self):
        print_invoice(self, self.conn, self._save_invoice())

    def load(self, invoice_id):
        """بيفتح فاتورة موجودة للتعديل. بيرجع True لو نجح."""
        return bool(safe_call(self, self._load, invoice_id))

    def _load(self, invoice_id):
        data = invoices.get_invoice(self.conn, invoice_id)
        h = data["invoice"]
        if h["kind"] != self.kind or h["status"] != "active":
            raise ValidationError("الفاتورة دي ملغية أو من نوع تاني")
        self.refresh()
        for combo, val in ((self.party, h["party_id"]), (self.wh, h["warehouse_id"])):
            i = combo.findData(val)
            if i >= 0:
                combo.setCurrentIndex(i)
        self.date.setText(h["invoice_date"])
        self.note.setText(h["note"])
        self.items = [(r["product_id"], r["name"], plain_qty(r["qty_m"]), plain_money(r["unit_price_c"]))
                      for r in data["items"]]
        self.discount.setText(plain_money(h["discount_c"]))
        self.paid.setText(plain_money(h["paid_c"]))
        self.edit_id = invoice_id
        self.title.setText(f"تعديل {self.info['title']} رقم {h['number']}")
        self.recalc()
        return True


class InvoicesListPage(QWidget):
    def __init__(self, conn, kind, on_open):
        super().__init__()
        self.conn, self.kind, self.on_open = conn, kind, on_open
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 14, 18, 14)
        v.setSpacing(12)
        flt = card()
        fl = QGridLayout(flt)
        fl.setContentsMargins(16, 10, 16, 10)
        fl.setHorizontalSpacing(12)
        party_label = invoices.KINDS[kind]["party_label"]
        self.f_number, self.f_party = QLineEdit(), QLineEdit()
        self.f_from, self.f_to = QLineEdit(), QLineEdit()
        self.f_number.setPlaceholderText("رقم")
        self.f_party.setPlaceholderText("جزء من الاسم")
        self.f_from.setPlaceholderText("2026-01-01")
        self.f_to.setPlaceholderText("2026-12-31")
        self.f_unpaid = QCheckBox("اللي عليها متبقي بس")
        for i, (t, w) in enumerate((("رقم الفاتورة", self.f_number), (party_label, self.f_party),
                                    ("من تاريخ", self.f_from), ("إلى تاريخ", self.f_to))):
            fl.addWidget(field_label(t), 0, i)
            fl.addWidget(w, 1, i)
            w.returnPressed.connect(self.refresh)
        fl.addWidget(self.f_unpaid, 1, 4)
        fl.addWidget(button("بحث", "primary", self.refresh), 1, 5)
        fl.addWidget(button("مسح الفلتر", "", self.clear_filter), 1, 6)
        fl.setColumnStretch(1, 2)
        v.addWidget(flt)
        self.count = QLabel("")
        self.count.setStyleSheet("color:#64748b")
        v.addWidget(self.count)
        self.table = make_table(["الرقم", "التاريخ", "الطرف", "الإجمالي", "المدفوع", "المتبقي"])
        v.addWidget(self.table, 1)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(button("فتح للتعديل", "primary", self.open_edit))
        row.addWidget(button("طباعة", "success", self.print_selected))
        row.addWidget(button("عرض PDF", "", self.open_pdf))
        row.addWidget(button("حذف الفاتورة", "danger", self.delete))
        row.addStretch(1)
        v.addLayout(row)

    @guard
    def refresh(self):
        rows = invoices.list_invoices(self.conn, self.kind, number=self.f_number.text(), party=self.f_party.text(),
                                      date_from=self.f_from.text(), date_to=self.f_to.text(),
                                      unpaid_only=self.f_unpaid.isChecked())
        filtered = any(e.text().strip() for e in (self.f_number, self.f_party, self.f_from, self.f_to)) \
            or self.f_unpaid.isChecked()
        self.count.setText(f"عدد الفواتير: {len(rows)}" + (" (نتيجة الفلتر)" if filtered else ""))
        self.table.setRowCount(len(rows))
        for r, i in enumerate(rows):
            vals = (i["number"], i["invoice_date"], i["party_name"], fmt_money(i["total_c"]),
                    fmt_money(i["paid_c"]), fmt_money(i["remaining_c"]))
            for c, val in enumerate(vals):
                self.table.setItem(r, c, cell(val, data=i["id"] if c == 0 else None))

    @guard
    def clear_filter(self):
        for e in (self.f_number, self.f_party, self.f_from, self.f_to):
            e.clear()
        self.f_unpaid.setChecked(False)
        self.refresh()

    def _need(self):
        iid = selected_id(self.table)
        if iid is None:
            raise ValidationError("اختر فاتورة من الجدول الأول")
        return iid

    @guard
    def open_edit(self):
        self.on_open(self._need())

    @guard
    def print_selected(self):
        print_invoice(self, self.conn, self._need())

    @guard
    def open_pdf(self):
        open_invoice_pdf(self, self.conn, self._need())

    @guard
    def delete(self):
        iid = self._need()
        if confirm(self, DELETE_WARNING):
            invoices.delete_invoice(self.conn, iid)
            self.refresh()
            QMessageBox.information(self, "تم", "تم حذف الفاتورة ✔")


class InvoicesTab(QWidget):
    def __init__(self, conn, kind):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        self.inner = QTabWidget()
        self.editor = InvoicePage(conn, kind)
        self.listing = InvoicesListPage(conn, kind, self.open_invoice)
        self.inner.addTab(self.editor, "فاتورة")
        self.inner.addTab(self.listing, "الفواتير السابقة")
        v.addWidget(self.inner)
        self.inner.currentChanged.connect(self.refresh)
        self.refresh()

    def open_invoice(self, invoice_id):
        if self.editor.load(invoice_id):
            self.inner.setCurrentIndex(0)

    def refresh(self, *_):
        self.inner.currentWidget().refresh()
