from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from ..logic import inventory, warehouses
from ..logic.errors import ValidationError
from ..logic.money import fmt_qty
from .common import button, card, cell, confirm, field_label, guard, make_table, selected_id


class WarehousesTab(QWidget):
    def __init__(self, conn):
        super().__init__()
        self.conn = conn
        h = QHBoxLayout(self)
        h.setContentsMargins(18, 16, 18, 16)
        h.setSpacing(14)
        left, right = QVBoxLayout(), QVBoxLayout()
        h.addLayout(left, 1)
        h.addLayout(right, 1)

        self.table = make_table(["المخزن", "الموقع"])
        self.table.itemSelectionChanged.connect(self.on_select)
        left.addWidget(self.table, 1)
        box = card()
        cl = QVBoxLayout(box)
        cl.setContentsMargins(16, 14, 16, 14)
        self.name, self.loc, self.notes = QLineEdit(), QLineEdit(), QLineEdit()
        for t, w in (("اسم المخزن", self.name), ("الموقع", self.loc), ("ملاحظات", self.notes)):
            cl.addWidget(field_label(t))
            cl.addWidget(w)
        b = QHBoxLayout()
        for t, kind, fn in (("إضافة", "success", self.add), ("تعديل", "primary", self.edit),
                            ("حذف", "danger", self.delete), ("تفريغ", "", self.clear_form)):
            b.addWidget(button(t, kind, fn))
        cl.addLayout(b)
        left.addWidget(box)

        self.title = QLabel("أرصدة المخزن المحدد")
        self.title.setStyleSheet("font-size:16px;font-weight:bold")
        right.addWidget(self.title)
        self.bal = make_table(["الصنف", "الرصيد"])
        right.addWidget(self.bal, 1)
        self.refresh()

    @guard
    def refresh(self):
        rows = warehouses.list_warehouses(self.conn)
        self.table.setRowCount(len(rows))
        for r, w in enumerate(rows):
            self.table.setItem(r, 0, cell(w["name"], data=w["id"]))
            self.table.setItem(r, 1, cell(w["location"]))
        self.bal.setRowCount(0)

    @guard
    def on_select(self):
        wid = selected_id(self.table)
        if wid is None:
            return
        w = inventory.get_warehouse(self.conn, wid)
        self.name.setText(w["name"])
        self.loc.setText(w["location"])
        self.notes.setText(w["notes"])
        self.title.setText(f"أرصدة: {w['name']}")
        rows = inventory.stock_table(self.conn, wid)
        self.bal.setRowCount(len(rows))
        for r, p in enumerate(rows):
            low = p["qty_m"] <= p["min_qty_m"]
            self.bal.setItem(r, 0, cell(p["name"], bg="#fff1f2" if low else None, fg="#9f1239" if low else None))
            self.bal.setItem(r, 1, cell(fmt_qty(p["qty_m"]), bg="#fff1f2" if low else None, fg="#9f1239" if low else None))

    def _need(self):
        wid = selected_id(self.table)
        if wid is None:
            raise ValidationError("اختر مخزن من الجدول الأول")
        return wid

    @guard
    def add(self):
        warehouses.create(self.conn, self.name.text(), self.loc.text(), self.notes.text())
        self.clear_form()
        self.refresh()

    @guard
    def edit(self):
        warehouses.update(self.conn, self._need(), self.name.text(), self.loc.text(), self.notes.text())
        self.refresh()

    @guard
    def delete(self):
        wid = self._need()
        if confirm(self, "حذف المخزن؟"):
            warehouses.deactivate(self.conn, wid)
            self.clear_form()
            self.refresh()

    @guard
    def clear_form(self):
        self.table.clearSelection()
        for e in (self.name, self.loc, self.notes):
            e.clear()
        self.bal.setRowCount(0)
        self.title.setText("أرصدة المخزن المحدد")
