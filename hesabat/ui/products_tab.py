from PySide6.QtWidgets import QComboBox, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QVBoxLayout, QWidget

from ..logic import inventory, products, warehouses
from ..logic.money import fmt_money, fmt_qty, plain_money, plain_qty
from .common import ROLE, button, card, cell, confirm, fill_combo, field_label, guard, make_table, selected_id


class ProductsTab(QWidget):
    HEADS = ["الرقم", "الصنف", "آخر سعر شراء", "متوسط التكلفة", "سعر البيع", "الكمية الكلية", "حد التنبيه"]
    FIELDS = ["الصنف", "سعر الشراء", "سعر البيع", "الكمية الافتتاحية", "حد التنبيه"]
    HINTS = ["مثال: سكر 1 كجم", "0", "0", "0", "0"]
    QTY_NEW, QTY_EDIT = "الكمية الافتتاحية", "الكمية في المخزن"

    def __init__(self, conn):
        super().__init__()
        self.conn = conn
        self.locked = False       # true لما يكون فيه صنف محمّل في الحقول للتعديل
        self._loaded_qty = ""     # نص الكمية وقت التحميل: بنعرف بيه لو المستخدم غيّرها ولا لأ
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(14)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("🔍 ابحث بالاسم أو برقم الصنف...")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        self.count = QLabel("")
        self.count.setStyleSheet("color:#64748b")
        bar.addWidget(self.search, 1)
        bar.addWidget(self.count)
        v.addLayout(bar)
        self.table = make_table(self.HEADS)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)  # عمود الرقم ضيق
        self.table.itemSelectionChanged.connect(self.on_select)
        v.addWidget(self.table, 1)

        box = card()
        cl = QVBoxLayout(box)
        cl.setContentsMargins(16, 14, 16, 14)
        cl.setSpacing(12)
        g = QGridLayout()
        g.setHorizontalSpacing(12)
        self.f, self.labels = [], []
        for i, (h, hint) in enumerate(zip(self.FIELDS, self.HINTS)):
            lab = field_label(h)
            self.labels.append(lab)
            g.addWidget(lab, 0, i)
            e = QLineEdit()
            e.setPlaceholderText(hint)
            self.f.append(e)
            g.addWidget(e, 1, i)
        self.f[3].setToolTip("عند الإضافة: الكمية الافتتاحية في المخزن المختار.\n"
                             "عند التعديل: الكمية الحالية في المخزن المختار، وتغييرها بيتسجل «تسوية» بالفرق.")
        self.wh = QComboBox()                         # المخزن اللي الكمية بتخصه
        g.addWidget(field_label("المخزن"), 0, 5)
        g.addWidget(self.wh, 1, 5)
        self.wh.currentIndexChanged.connect(self.on_wh)
        g.setColumnStretch(0, 2)
        for i in range(1, 6):
            g.setColumnStretch(i, 1)
        cl.addLayout(g)
        b = QHBoxLayout()
        b.setSpacing(10)
        for t, kind, fn in (("إضافة", "success", self.add), ("تعديل", "primary", self.edit),
                            ("حذف", "danger", self.delete), ("تفريغ الحقول", "", self.clear_form)):
            b.addWidget(button(t, kind, fn))
        b.addStretch()
        cl.addLayout(b)
        v.addWidget(box)
        self.refresh()

    @guard
    def refresh(self):
        fill_combo(self.wh, warehouses.list_warehouses(self.conn))
        rows = products.list_products(self.conn, self.search.text())
        total = products.count(self.conn)
        keep = selected_id(self.table)       # نحافظ على الصنف المحدد بعد البحث/التحديث
        self.table.setRowCount(len(rows))
        for r, p in enumerate(rows):
            low = p["qty_m"] <= p["min_qty_m"]
            vals = [str(p["id"]), p["name"], fmt_money(p["buy_price_c"]), fmt_money(p["avg_cost_c"]),
                    fmt_money(p["sell_price_c"]), fmt_qty(p["qty_m"]), fmt_qty(p["min_qty_m"])]
            for c, val in enumerate(vals):
                self.table.setItem(r, c, cell(val, data=p["id"] if c == 0 else None,
                                              bg="#fff1f2" if low else None, fg="#9f1239" if low else None))
        self.count.setText(f"عدد الأصناف: {len(rows)}" + (f" من {total}" if len(rows) != total else ""))
        if keep is not None:
            for r in range(self.table.rowCount()):
                if self.table.item(r, 0).data(ROLE) == keep:
                    self.table.blockSignals(True)    # من غير ما نكتب فوق اللي المستخدم بيعدّله في الحقول
                    self.table.selectRow(r)
                    self.table.blockSignals(False)
                    break
            if self.locked and self.f[3].text().strip() == self._loaded_qty:
                self._fill_qty()                     # الكمية اتغيّرت (بيع/شراء) ومفيش تعديل من المستخدم: نحدّثها

    def _fill_qty(self):
        """بيعرض كمية الصنف المحدد في المخزن المختار."""
        pid, wid = selected_id(self.table), self.wh.currentData()
        if pid is None or wid is None:
            return
        self._loaded_qty = plain_qty(inventory.balance(self.conn, pid, wid))
        self.f[3].setText(self._loaded_qty)

    @guard
    def on_select(self):
        pid = selected_id(self.table)
        if pid is None:
            return
        p = products.get(self.conn, pid)
        self.f[0].setText(p["name"])
        self.f[1].setText(plain_money(p["buy_price_c"]))
        self.f[2].setText(plain_money(p["sell_price_c"]))
        self.f[4].setText(plain_qty(p["min_qty_m"]))
        self.locked = True
        self.labels[3].setText(self.QTY_EDIT)
        self._fill_qty()

    @guard
    def on_wh(self):
        if self.locked:
            self._fill_qty()                         # غيّرت المخزن: نعرض كمية الصنف فيه

    def _texts(self):
        return [e.text() for e in self.f]

    def _qty_changed(self, qty):
        """هل المستخدم غيّر الكمية بإيده؟ (فاضية أو زي ما اتحمّلت = لأ)"""
        q = qty.strip()
        return q != "" and q != self._loaded_qty

    @guard
    def add(self):
        n, buy, sell, qty, mn = self._texts()
        # لو فيه صنف محمّل ومغيّرناش الكمية، مبنورّثش كميته للصنف الجديد
        opening = qty if (not self.locked or self._qty_changed(qty)) else "0"
        products.create(self.conn, n, buy, sell, mn, opening, self.wh.currentData())
        self.clear_form()
        self.refresh()

    @guard
    def edit(self):
        pid = selected_id(self.table)
        if pid is None:
            raise_select()
        n, buy, sell, qty, mn = self._texts()
        products.update(self.conn, pid, n, buy, sell, mn, qty if self._qty_changed(qty) else None,
                        self.wh.currentData())
        self.refresh()
        self._fill_qty()                             # نعرض الكمية الجديدة كمرجع للتعديل الجاي

    @guard
    def delete(self):
        pid = selected_id(self.table)
        if pid is None:
            raise_select()
        if confirm(self, "حذف الصنف؟ (هيختفي من القوائم وتفضل حركاته القديمة في السجل)"):
            products.deactivate(self.conn, pid)
            self.clear_form()
            self.refresh()

    @guard
    def clear_form(self):
        self.table.clearSelection()
        for e in self.f:
            e.clear()
        self.locked = False
        self._loaded_qty = ""
        self.labels[3].setText(self.QTY_NEW)


def raise_select():
    from ..logic.errors import ValidationError
    raise ValidationError("اختر صنف من الجدول الأول")
