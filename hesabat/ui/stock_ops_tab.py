from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout, QLabel, QLineEdit, QTabWidget,
                               QVBoxLayout, QWidget)

from ..logic import inventory, products, warehouses
from ..logic.errors import ValidationError
from ..logic.money import fmt_qty, parse_qty
from .search_combo import SearchCombo
from .common import ROLE, button, card, cell, confirm, fill_combo, field_label, guard, make_table

INFO_STYLE = ("color:#15803d;background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;"
              "padding:10px;font-size:15px;font-weight:bold")


class TransferPage(QWidget):
    def __init__(self, conn):
        super().__init__()
        self.conn = conn
        outer = QHBoxLayout(self)
        outer.setContentsMargins(18, 24, 18, 18)
        outer.addStretch(1)
        box = card()
        box.setMinimumWidth(420)
        box.setMaximumWidth(560)
        v = QVBoxLayout(box)
        v.setContentsMargins(26, 22, 26, 22)
        v.setSpacing(10)
        t = QLabel("تحويل أصناف بين المخازن")
        t.setStyleSheet("font-size:19px;font-weight:bold")
        v.addWidget(t)
        self.src, self.dst = QComboBox(), QComboBox()
        self.prod = SearchCombo(by_number=True, placeholder="اكتب اسم الصنف أو رقمه")
        self.qty, self.note = QLineEdit(), QLineEdit()
        self.qty.setPlaceholderText("0")
        for text, w in (("من مخزن", self.src), ("إلى مخزن", self.dst), ("الصنف", self.prod),
                        ("الكمية", self.qty), ("ملاحظة (اختياري)", self.note)):
            v.addWidget(field_label(text))
            v.addWidget(w)
        self.avail = QLabel("")
        self.avail.setStyleSheet("color:#64748b")
        v.addWidget(self.avail)
        v.addWidget(button("تنفيذ التحويل", "primary", self.do))
        self.info = QLabel("")
        self.info.setStyleSheet(INFO_STYLE)
        self.info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info.setVisible(False)
        v.addWidget(self.info)
        outer.addWidget(box, 0, Qt.AlignmentFlag.AlignTop)
        outer.addStretch(1)
        self.src.currentIndexChanged.connect(self.update_avail)
        self.prod.currentIndexChanged.connect(self.update_avail)

    @guard
    def refresh(self):
        whs = warehouses.list_warehouses(self.conn)
        fill_combo(self.src, whs)
        fill_combo(self.dst, whs)
        if self.dst.count() > 1 and self.dst.currentData() == self.src.currentData():
            self.dst.setCurrentIndex((self.dst.currentIndex() + 1) % self.dst.count())
        fill_combo(self.prod, products.list_products(self.conn))
        self.update_avail()

    @guard
    def update_avail(self):
        pid, wid = self.prod.currentData(), self.src.currentData()
        if pid is None or wid is None:
            self.avail.setText("")
        else:
            self.avail.setText(f"المتاح في المخزن المصدر: {fmt_qty(inventory.balance(self.conn, pid, wid))}")

    @guard
    def do(self):
        src, dst, pid = self.src.currentData(), self.dst.currentData(), self.prod.value()
        if src is None or dst is None or pid is None:
            raise ValidationError("اختر المخزنين والصنف")
        inventory.transfer(self.conn, src, dst, [(pid, self.qty.text())], self.note.text())
        self.info.setText("تم التحويل بنجاح ✔")
        self.info.setVisible(True)
        self.qty.clear()
        self.note.clear()
        self.update_avail()


class StocktakePage(QWidget):
    def __init__(self, conn):
        super().__init__()
        self.conn = conn
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(12)
        top = QHBoxLayout()
        top.addWidget(field_label("المخزن"))
        self.wh = QComboBox()
        self.wh.currentIndexChanged.connect(self.load)
        top.addWidget(self.wh, 1)
        v.addLayout(top)
        hint = QLabel("اكتب الرصيد الفعلي (اللي عديته) قدّام كل صنف. الأصناف اللي هتسيبها فاضية مش هتتعدل.")
        hint.setStyleSheet("color:#64748b")
        v.addWidget(hint)
        self.table = make_table(["الصنف", "الرصيد الدفتري", "الرصيد الفعلي", "الفرق"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.AllEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.table.itemChanged.connect(self.on_changed)
        v.addWidget(self.table, 1)
        v.addWidget(button("اعتماد الجرد وتسوية الفروق", "primary", self.apply))

    @guard
    def refresh(self):
        fill_combo(self.wh, warehouses.list_warehouses(self.conn))
        self.load()

    @guard
    def load(self):
        wid = self.wh.currentData()
        rows = inventory.stock_table(self.conn, wid) if wid is not None else []
        self.table.blockSignals(True)
        self.table.setRowCount(len(rows))
        for r, p in enumerate(rows):
            self.table.setItem(r, 0, cell(p["name"], data=p["id"]))
            self.table.setItem(r, 1, cell(fmt_qty(p["qty_m"]), data=p["qty_m"]))
            self.table.setItem(r, 2, cell("", editable=True))
            self.table.setItem(r, 3, cell(""))
        self.table.blockSignals(False)

    def on_changed(self, item):
        if item.column() != 2:
            return
        row = item.row()
        system = self.table.item(row, 1).data(ROLE)
        diff_item, text = self.table.item(row, 3), item.text().strip()
        if text == "":
            diff_item.setText("")
            return
        try:
            diff = parse_qty(text, allow_zero=True) - system
            diff_item.setText(fmt_qty(diff))
        except ValidationError:
            diff_item.setText("⚠ رقم غير صحيح")

    @guard
    def apply(self):
        wid = self.wh.currentData()
        counts = {self.table.item(r, 0).data(ROLE): self.table.item(r, 2).text()
                  for r in range(self.table.rowCount()) if self.table.item(r, 2).text().strip()}
        if wid is None or not counts:
            raise ValidationError("اكتب الرصيد الفعلي لصنف واحد على الأقل")
        if not confirm(self, f"اعتماد جرد {len(counts)} صنف؟ الفروق هتتسجل كحركات تسوية."):
            return
        _sid, changed = inventory.apply_stocktake(self.conn, wid, counts)
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(self, "تم", f"تم اعتماد الجرد. عدد الأصناف اللي اتسوّت: {changed}")
        self.load()


class StockOpsTab(QWidget):
    def __init__(self, conn):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        self.inner = QTabWidget()
        self.transfer, self.count = TransferPage(conn), StocktakePage(conn)
        self.inner.addTab(self.transfer, "تحويل بين المخازن")
        self.inner.addTab(self.count, "جرد وتسوية")
        v.addWidget(self.inner)
        self.inner.currentChanged.connect(self.refresh)

    def refresh(self, *_):
        self.inner.currentWidget().refresh()
