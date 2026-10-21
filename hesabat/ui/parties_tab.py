from PySide6.QtWidgets import QDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from ..logic import parties
from ..logic.errors import ValidationError
from ..logic.money import fmt_money, plain_money
from .common import button, card, cell, confirm, field_label, guard, make_table, safe_call, selected_id
from .invoices_tab import InvoiceViewDialog


class StatementDialog(QDialog):
    def __init__(self, parent, conn, data):
        super().__init__(parent)
        self.conn, self.invoice_ids = conn, data["invoice_ids"]
        self.setWindowTitle(f"كشف حساب - {data['party']['name']}")
        self.resize(760, 480)
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 16, 16, 16)
        t = make_table(["التاريخ", "البيان", "ملاحظة", "المبلغ", "الرصيد"])
        t.setRowCount(len(data["rows"]))
        for r, row in enumerate(data["rows"]):
            date, kind, note, amount, running = row
            for c, val in enumerate((date, kind, note, fmt_money(amount), fmt_money(running))):
                t.setItem(r, c, cell(val))
        t.cellClicked.connect(self.open_invoice)
        v.addWidget(t, 1)
        hint = QLabel("اضغط على أي فاتورة عشان تشوف تفاصيلها كاملة")
        hint.setStyleSheet("color:#64748b")
        v.addWidget(hint)
        total = QLabel(f"الرصيد الحالي: {fmt_money(data['balance_c'])}")
        total.setStyleSheet("font-size:17px;font-weight:bold")
        v.addWidget(total)
        v.addWidget(button("إغلاق", "primary", self.accept))

    def open_invoice(self, row, _col=0):
        iid = self.invoice_ids[row] if 0 <= row < len(self.invoice_ids) else None
        if iid is not None:
            safe_call(self, lambda: InvoiceViewDialog(self, self.conn, iid).exec())


class PartiesTab(QWidget):
    HEADS = ["الاسم", "التليفون", "العنوان", "الرصيد"]
    FIELDS = ["الاسم", "التليفون", "العنوان", "ملاحظات", "رصيد افتتاحي"]

    def __init__(self, conn, kind):
        super().__init__()
        self.conn, self.kind = conn, kind
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(12)
        self.table = make_table(self.HEADS)
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
        rows = parties.list_parties(self.conn, self.kind)
        self.table.setRowCount(len(rows))
        for r, p in enumerate(rows):
            vals = (p["name"], p["phone"], p["address"], fmt_money(p["balance_c"]))
            for c, val in enumerate(vals):
                self.table.setItem(r, c, cell(val, data=p["id"] if c == 0 else None))

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
        StatementDialog(self, self.conn, parties.statement(self.conn, self.kind, self._need())).exec()
