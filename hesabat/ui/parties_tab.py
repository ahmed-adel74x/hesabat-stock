from PySide6.QtWidgets import QDialog, QHeaderView, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from ..logic import parties, party_reports
from ..logic.errors import ValidationError
from ..logic.money import fmt_money, plain_money
from .common import button, card, cell, confirm, field_label, guard, make_table, safe_call, selected_id
from .invoices_tab import InvoiceViewDialog
from .printing import print_html


class StatementDialog(QDialog):
    def __init__(self, parent, conn, data, kind=None, on_change=None):
        super().__init__(parent)
        self.conn, self.kind, self.pid = conn, kind, data["party"]["id"]
        self.on_change = on_change
        self.invoice_ids = data["invoice_ids"]
        self.setWindowTitle(f"كشف حساب - {data['party']['name']}")
        self.resize(820, 540)
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 16, 16, 16)
        self.table = make_table(["التاريخ", "البيان", "ملاحظة", "المبلغ", "الرصيد", "مسح"])
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.table.cellClicked.connect(self.open_invoice)
        v.addWidget(self.table, 1)
        hint = QLabel("اضغط على أي فاتورة عشان تشوف تفاصيلها وتطبعها أو تعدّلها أو تمسحها")
        hint.setStyleSheet("color:#64748b")
        v.addWidget(hint)
        self.total = QLabel()
        self.total.setStyleSheet("font-size:17px;font-weight:bold")
        v.addWidget(self.total)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(button("طباعة كل التعاملات", "success", self.print_all))
        row.addWidget(button("طباعة المتبقي (الفواتير والباقي)", "success", self.print_dues))
        row.addStretch(1)
        row.addWidget(button("إغلاق", "primary", self.accept))
        v.addLayout(row)
        self.show_data(data)

    def show_data(self, data):
        self.invoice_ids = data["invoice_ids"]
        t = self.table
        t.setRowCount(len(data["rows"]))
        for r, row in enumerate(data["rows"]):
            date, kind, note, amount, running = row
            for c, val in enumerate((date, kind, note, fmt_money(amount), fmt_money(running))):
                t.setItem(r, c, cell(val))
            t.setItem(r, 5, cell(""))
            if data["removable"][r]:               # سطر ملغي قبل كده: زرار مسح جنبه
                b = button("🗑", "danger")
                b.setToolTip("مسح السطر الملغي ده من كشف الحساب (الرصيد مش هيتغير)")
                b.clicked.connect(lambda _=False, lid=data["ledger_ids"][r]: safe_call(self, self._remove_cancelled, lid))
                t.setCellWidget(r, 5, b)
        self.total.setText(f"الرصيد الحالي: {fmt_money(data['balance_c'])}")

    def reload(self):
        self.show_data(parties.statement(self.conn, self.kind, self.pid))

    def _remove_cancelled(self, ledger_id):
        if confirm(self, "تمسح السطر الملغي ده ومقابله من كشف الحساب؟\nالرصيد مش هيتغير."):
            parties.remove_cancelled(self.conn, self.kind, self.pid, ledger_id)
            self.reload()

    def open_invoice(self, row, _col=0):
        iid = self.invoice_ids[row] if 0 <= row < len(self.invoice_ids) else None
        if iid is not None:
            safe_call(self, self._view_invoice, iid)

    def _view_invoice(self, iid):
        dlg = InvoiceViewDialog(self, self.conn, iid, allow_change=True)
        dlg.exec()
        if dlg.action == "deleted":
            self.reload()                          # الكشف نفسه يتحدّث، وباقي البرنامج يتحدّث من تحت
            if self.on_change:
                self.on_change(iid, deleted=True)
        elif dlg.action == "edit":
            self.accept()                          # نقفل الكشف ونفتح الفاتورة في شاشة التعديل
            if self.on_change:
                self.on_change(iid, deleted=False)

    @guard
    def print_all(self):
        print_html(self, party_reports.statement_html(self.conn, self.kind, self.pid), False, "statement")

    @guard
    def print_dues(self):
        print_html(self, party_reports.dues_html(self.conn, self.kind, self.pid), False, "dues")


class PartiesTab(QWidget):
    HEADS = ["الاسم", "التليفون", "العنوان", "الرصيد"]
    FIELDS = ["الاسم", "التليفون", "العنوان", "ملاحظات", "رصيد افتتاحي"]

    def __init__(self, conn, kind):
        super().__init__()
        self.conn, self.kind = conn, kind
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(12)
        self.search = QLineEdit()
        self.search.setPlaceholderText("🔍 ابحث باسم " + ("العميل" if kind == "customer" else "المورد") + " أو تليفونه...")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        v.addWidget(self.search)
        self.table = make_table(self.HEADS[:3] + ["مبلغ مستحق على العميل" if kind == "customer" else "مبلغ مستحق للمورد"])
        self.table.itemSelectionChanged.connect(self.on_select)
        v.addWidget(self.table, 1)
        hint = QLabel("الرصيد الموجب = مبلغ مستحق " + ("على العميل" if kind == "customer" else "للمورد") +
                      "  |  السالب عكس ذلك")
        hint.setStyleSheet("color:#64748b")
        v.addWidget(hint)

        box = card()
        cl = QVBoxLayout(box)
        cl.setContentsMargins(16, 14, 16, 14)
        cl.setSpacing(12)
        g = QGridLayout()
        g.setHorizontalSpacing(12)
        self.f = []
        for i, h in enumerate(self.FIELDS):
            g.addWidget(field_label(h), 0, i)
            e = QLineEdit()
            self.f.append(e)
            g.addWidget(e, 1, i)
        self.f[4].setPlaceholderText("0")
        g.setColumnStretch(0, 2)
        g.setColumnStretch(2, 2)
        cl.addLayout(g)
        b = QHBoxLayout()
        b.setSpacing(10)
        for t, k, fn in (("إضافة", "success", self.add), ("تعديل", "primary", self.edit),
                         ("حذف", "danger", self.delete), ("تفريغ", "", self.clear_form),
                         ("كشف حساب", "primary", self.statement)):
            b.addWidget(button(t, k, fn))
        b.addStretch()
        cl.addLayout(b)
        v.addWidget(box)
        self.refresh()

    @guard
    def refresh(self):
        rows = parties.search(parties.list_parties(self.conn, self.kind), self.search.text())
        keep = selected_id(self.table)
        self.table.setRowCount(len(rows))
        for r, p in enumerate(rows):
            vals = (p["name"], p["phone"], p["address"], fmt_money(p["balance_c"]))
            for c, val in enumerate(vals):
                self.table.setItem(r, c, cell(val, data=p["id"] if c == 0 else None))
            if keep is not None and p["id"] == keep:
                self.table.selectRow(r)            # الصف المحدد يفضل محدد بعد البحث/التحديث

    @guard
    def on_select(self):
        pid = selected_id(self.table)
        if pid is None:
            return
        p = parties.get(self.conn, self.kind, pid)
        for e, val in zip(self.f, (p["name"], p["phone"], p["address"], p["notes"], plain_money(p["opening_balance_c"]))):
            e.setText(val)

    def _need(self):
        pid = selected_id(self.table)
        if pid is None:
            raise ValidationError("اختر من الجدول الأول")
        return pid

    def _vals(self):
        return [e.text() for e in self.f]

    @guard
    def add(self):
        n, ph, ad, no, ob = self._vals()
        parties.create(self.conn, self.kind, n, ph, ad, no, ob)
        self.clear_form()
        self.refresh()

    @guard
    def edit(self):
        n, ph, ad, no, ob = self._vals()
        parties.update(self.conn, self.kind, self._need(), n, ph, ad, no, ob)
        self.refresh()

    @guard
    def delete(self):
        pid = self._need()
        if confirm(self, "حذف؟ (هيختفي من القوائم وتفضل بياناته في السجل)"):
            parties.deactivate(self.conn, self.kind, pid)
            self.clear_form()
            self.refresh()

    @guard
    def clear_form(self):
        self.table.clearSelection()
        for e in self.f:
            e.clear()

    @guard
    def statement(self):
        pid = self._need()
        StatementDialog(self, self.conn, parties.statement(self.conn, self.kind, pid), self.kind,
                        self._invoice_changed).exec()
        self.refresh()                             # الأرصدة في القائمة تتحدّث بعد أي تعديل/مسح

    def _invoice_changed(self, invoice_id, deleted):
        main = self.window()
        if deleted and hasattr(main, "invoice_deleted"):
            main.invoice_deleted(invoice_id)
        elif not deleted and hasattr(main, "edit_invoice"):
            main.edit_invoice(invoice_id)
