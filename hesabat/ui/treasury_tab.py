from PySide6.QtWidgets import (QComboBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QTabWidget,
                               QVBoxLayout, QWidget)

from ..logic import parties, treasury
from ..logic.errors import ValidationError
from ..logic.money import fmt_money, plain_money
from .search_combo import SearchCombo
from .common import (ROLE, button, card, cell, confirm, fill_combo, field_label, guard, make_table, selected_id,
                     stat_card)



class VouchersPage(QWidget):
    def __init__(self, conn):
        super().__init__()
        self.conn = conn
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 14, 18, 14)
        v.setSpacing(12)

        row = QHBoxLayout()
        row.setSpacing(12)
        f1, self.l_bal = stat_card("رصيد الخزينة الآن", "#2563eb")
        f2, self.l_in = stat_card("قبض اليوم", "#16a34a")
        f3, self.l_out = stat_card("صرف اليوم", "#ea580c")
        for f in (f1, f2, f3):
            row.addWidget(f)
        v.addLayout(row)

        box = card()
        g = QGridLayout(box)
        g.setContentsMargins(16, 14, 16, 14)
        g.setHorizontalSpacing(12)
        self.kind, self.ptype = QComboBox(), QComboBox()
        self.pname = SearchCombo(placeholder="اكتب الاسم")
        self.kind.addItem("سند قبض (داخل)", "receipt")
        self.kind.addItem("سند صرف (خارج)", "payment")
        self.ptype.addItem("عميل", "customer")
        self.ptype.addItem("مورد", "supplier")
        self.ptype.addItem("عام (مصروف / إيراد)", "")
        self.cat, self.amount, self.date, self.note = QLineEdit(), QLineEdit(), QLineEdit(), QLineEdit()
        self.cat.setPlaceholderText("مثال: إيجار، كهرباء")
        self.amount.setPlaceholderText("0")
        self.date.setText(treasury.today())
        fields = [("نوع السند", self.kind), ("الطرف", self.ptype), ("الاسم", self.pname), ("البيان (للعام)", self.cat),
                  ("المبلغ", self.amount), ("التاريخ", self.date), ("ملاحظة", self.note)]
        for i, (t, w) in enumerate(fields):
            g.addWidget(field_label(t), (i // 4) * 2, i % 4)
            g.addWidget(w, (i // 4) * 2 + 1, i % 4)
        g.addWidget(button("حفظ السند", "success", self.save), 3, 3)
        v.addWidget(box)
        self.ptype.currentIndexChanged.connect(self.on_type)

        op = QHBoxLayout()
        op.addWidget(field_label("الرصيد الافتتاحي للخزينة"))
        self.opening = QLineEdit()
        self.opening.setMaximumWidth(160)
        op.addWidget(self.opening)
        op.addWidget(button("حفظ", "primary", self.save_opening))
        op.addStretch(1)
        op.addWidget(button("إلغاء السند المحدد", "danger", self.void))
        v.addLayout(op)

        self.table = make_table(["التاريخ", "النوع", "الطرف / البيان", "المبلغ"])
        v.addWidget(self.table, 1)

    @guard
    def refresh(self):
        s = treasury.summary(self.conn)
        self.l_bal.setText(fmt_money(s["balance_c"]))
        self.l_in.setText(fmt_money(s["today_in"]))
        self.l_out.setText(fmt_money(s["today_out"]))
        self.opening.setText(plain_money(s["opening_c"]))
        self.on_type()
        rows = treasury.recent_entries(self.conn, 100)
        self.table.setRowCount(len(rows))
        for r, e in enumerate(rows):
            vals = (e["entry_date"], treasury.KIND_LABELS[e["kind"]], e["what"], fmt_money(e["amount_c"]))
            for c, val in enumerate(vals):
                self.table.setItem(r, c, cell(val, data=e["id"] if c == 0 else None))

    @guard
    def on_type(self):
        t = self.ptype.currentData()
        if t:
            fill_combo(self.pname, parties.list_parties(self.conn, t))
        else:
            self.pname.clear()
        self.pname.setEnabled(bool(t))
        self.cat.setEnabled(not t)

    @guard
    def save(self):
        t = self.ptype.currentData() or None
        pid = self.pname.value() if t else None
        if t and pid is None:
            raise ValidationError("اختر الاسم (أضف عميل أو مورد الأول لو القائمة فاضية)")
        treasury.add_voucher(self.conn, self.kind.currentData(), self.amount.text(), t, pid,
                             self.cat.text(), self.note.text(), self.date.text())
        self.amount.clear()
        self.cat.clear()
        self.note.clear()
        self.refresh()

    @guard
    def save_opening(self):
        treasury.set_opening(self.conn, self.opening.text())
        self.refresh()

    @guard
    def void(self):
        eid = selected_id(self.table)
        if eid is None:
            raise ValidationError("اختر سند من الجدول الأول")
        if confirm(self, "إلغاء السند؟ هيتمسح خالص وهيتشال أثره من الخزينة وحساب الطرف."):
            treasury.void_entry(self.conn, eid)
            self.refresh()


class StatementPage(QWidget):
    def __init__(self, conn):
        super().__init__()
        self.conn = conn
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 14, 18, 14)
        v.setSpacing(12)
        top = QHBoxLayout()
        self.dfrom, self.dto = QLineEdit(), QLineEdit()
        self.dfrom.setText(treasury.month_start())
        self.dto.setText(treasury.today())
        for t, w in (("من تاريخ", self.dfrom), ("إلى تاريخ", self.dto)):
            top.addWidget(field_label(t))
            top.addWidget(w)
        top.addWidget(button("عرض", "primary", self.refresh))
        top.addStretch(1)
        v.addLayout(top)
        row = QHBoxLayout()
        row.setSpacing(12)
        self.cards = {}
        for key, title, color in (("o", "رصيد أول المدة", "#64748b"), ("i", "إجمالي الوارد", "#16a34a"),
                                  ("x", "إجمالي الصادر", "#ea580c"), ("c", "رصيد آخر المدة", "#2563eb")):
            f, lab = stat_card(title, color)
            self.cards[key] = lab
            row.addWidget(f)
        v.addLayout(row)
        self.table = make_table(["التاريخ", "النوع", "البيان", "وارد", "صادر", "الرصيد"])
        v.addWidget(self.table, 1)

    @guard
    def refresh(self):
        st = treasury.statement(self.conn, self.dfrom.text(), self.dto.text())
        for k, val in (("o", st["opening_c"]), ("i", st["total_in"]), ("x", st["total_out"]), ("c", st["closing_c"])):
            self.cards[k].setText(fmt_money(val))
        self.table.setRowCount(len(st["rows"]))
        for r, e in enumerate(st["rows"]):
            vals = (e["date"], e["label"], e["text"], fmt_money(e["in_c"]) if e["in_c"] else "",
                    fmt_money(e["out_c"]) if e["out_c"] else "", fmt_money(e["running_c"]))
            for c, val in enumerate(vals):
                self.table.setItem(r, c, cell(val))


class ClosingPage(QWidget):
    def __init__(self, conn):
        super().__init__()
        self.conn = conn
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 14, 18, 14)
        v.setSpacing(12)
        self.info = QLabel("")
        self.info.setStyleSheet("font-size:15px")
        v.addWidget(self.info)
        box = card()
        g = QGridLayout(box)
        g.setContentsMargins(16, 14, 16, 14)
        g.setHorizontalSpacing(12)
        self.date, self.counted, self.note = QLineEdit(), QLineEdit(), QLineEdit()
        self.date.setText(treasury.today())
        self.counted.setPlaceholderText("اتركه فاضي لو مش هتجرد")
        for i, (t, w) in enumerate((("تاريخ التقفيل", self.date), ("النقدية الفعلية (اختياري)", self.counted),
                                    ("ملاحظة", self.note))):
            g.addWidget(field_label(t), 0, i)
            g.addWidget(w, 1, i)
        b = QHBoxLayout()
        b.addWidget(button("تقفيل اليوم", "primary", self.close))
        b.addWidget(button("إلغاء آخر تقفيل", "danger", self.reopen))
        b.addStretch(1)
        g.addLayout(b, 2, 0, 1, 3)
        v.addWidget(box)
        hint = QLabel("التقفيل بيمنع إضافة أو إلغاء أي سند بتاريخ التقفيل أو قبله. لو النقدية الفعلية اختلفت عن "
                      "الدفتري بيتسجل سند عجز/زيادة أوتوماتيك.")
        hint.setStyleSheet("color:#64748b")
        hint.setWordWrap(True)
        v.addWidget(hint)
        self.table = make_table(["التاريخ", "رصيد أول", "قبض", "صرف", "رصيد القفل", "الفعلي", "الفرق"])
        v.addWidget(self.table, 1)

    @guard
    def refresh(self):
        s = treasury.summary(self.conn)
        self.info.setText(f"رصيد الخزينة الدفتري: {fmt_money(s['balance_c'])}   |   آخر تقفيل: {s['last_close'] or 'لا يوجد'}")
        rows = treasury.list_closings(self.conn)
        self.table.setRowCount(len(rows))
        for r, c in enumerate(rows):
            counted = "" if c["counted_c"] is None else fmt_money(c["counted_c"])
            diff = "" if c["counted_c"] is None else fmt_money(c["diff_c"])
            vals = (c["close_date"], fmt_money(c["opening_c"]), fmt_money(c["receipts_c"]), fmt_money(c["payments_c"]),
                    fmt_money(c["closing_c"]), counted, diff)
            for i, val in enumerate(vals):
                self.table.setItem(r, i, cell(val))

    @guard
    def close(self):
        if not confirm(self, "تقفيل اليوم؟ مش هتقدر تعدّل سندات بتاريخ التقفيل أو قبله إلا بإلغاء التقفيل."):
            return
        treasury.close_day(self.conn, self.date.text(), self.counted.text(), self.note.text())
        self.counted.clear()
        self.note.clear()
        self.refresh()
        QMessageBox.information(self, "تم", "تم التقفيل ✔")

    @guard
    def reopen(self):
        if confirm(self, "إلغاء آخر تقفيل؟ (لو كان فيه سند عجز/زيادة تلقائي هيتلغي معاه)"):
            d = treasury.reopen_last_closing(self.conn)
            self.refresh()
            QMessageBox.information(self, "تم", f"اتلغى تقفيل {d}")


class TreasuryTab(QWidget):
    def __init__(self, conn):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        self.inner = QTabWidget()
        self.vouchers, self.stmt, self.closing = VouchersPage(conn), StatementPage(conn), ClosingPage(conn)
        self.inner.addTab(self.vouchers, "السندات")
        self.inner.addTab(self.stmt, "كشف الحركة")
        self.inner.addTab(self.closing, "التقفيل اليومي")
        v.addWidget(self.inner)
        self.inner.currentChanged.connect(self.refresh)
        self.refresh()

    def refresh(self, *_):
        self.inner.currentWidget().refresh()
