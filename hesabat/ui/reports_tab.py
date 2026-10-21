import traceback

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMessageBox, QScrollArea, QTableWidget, QTabWidget,
                               QVBoxLayout, QWidget)

from ..db.connection import db_file
from ..logic import export, parties, products, reports, treasury, warehouses
from ..logic.errors import ValidationError
from ..logic.money import fmt_money, fmt_qty
from . import printing
from .search_combo import SearchCombo
from .common import button, card, cell, field_label, guard, make_table, report_error, safe_call


class DashboardPage(QScrollArea):
    def __init__(self, conn):
        super().__init__()
        self.conn = conn
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        self.setWidget(inner)
        self.rl = QVBoxLayout(inner)
        self.rl.setContentsMargins(18, 14, 18, 18)
        self.rl.setSpacing(12)
        self.vals = {}
        self.section("📅 اليوم", [("ts", "المبيعات", "#2563eb"), ("tp", "الربح", "#16a34a"), ("tb", "المشتريات", "#ea580c")])
        self.section("🗓️ الشهر", [("ms", "المبيعات", "#2563eb"), ("mp", "الربح", "#16a34a"), ("mb", "المشتريات", "#ea580c")])
        self.section("📦 المخزون", [("cv", "القيمة بالتكلفة", "#7c3aed"), ("sv", "القيمة بسعر البيع", "#7c3aed"),
                                     ("ep", "الربح المتوقع", "#16a34a"), ("cnt", "عدد الأصناف", "#64748b")])
        lbl = QLabel("⚠️ أصناف قاربت على الخلوص")
        lbl.setStyleSheet("font-size:17px;font-weight:bold;margin-top:6px")
        self.rl.addWidget(lbl)
        self.low = QTableWidget(0, 2)
        self.low.setHorizontalHeaderLabels(["الصنف", "المتبقي"])
        self.low.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.low.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.low.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.low.verticalHeader().setVisible(False)
        self.low.setShowGrid(False)
        self.low.setMinimumHeight(170)
        self.rl.addWidget(self.low)
        self.refresh()

    def card(self, title, color):
        f = QFrame()
        f.setObjectName("card")
        l = QVBoxLayout(f)
        l.setContentsMargins(16, 12, 16, 12)
        t = QLabel(title)
        t.setStyleSheet("color:#64748b;font-size:13px")
        v = QLabel("0")
        v.setStyleSheet(f"color:{color};font-size:26px;font-weight:bold")
        l.addWidget(t)
        l.addWidget(v)
        return f, v

    def section(self, text, items):
        lbl = QLabel(text)
        lbl.setStyleSheet("font-size:17px;font-weight:bold;margin-top:6px")
        self.rl.addWidget(lbl)
        row = QHBoxLayout()
        row.setSpacing(12)
        for key, title, color in items:
            f, v = self.card(title, color)
            self.vals[key] = v
            row.addWidget(f)
        self.rl.addLayout(row)

    @guard
    def refresh(self):
        d = reports.dashboard(self.conn)
        for k, lab in self.vals.items():
            lab.setText(str(d[k]) if k == "cnt" else fmt_money(d[k]))
        low = d["low"]
        self.low.setRowCount(len(low) or 1)
        if not low:
            self.low.setItem(0, 0, cell("✅ كل الأصناف متوفرة", fg="#15803d"))
            self.low.setSpan(0, 0, 1, 2)
            return
        self.low.clearSpans()
        for r, (name, q) in enumerate(low):
            self.low.setItem(r, 0, cell(name, bg="#fff1f2", fg="#9f1239"))
            self.low.setItem(r, 1, cell(fmt_qty(q), bg="#fff1f2", fg="#9f1239"))


class _Signals(QObject):
    done = Signal(object)
    invalid = Signal(str)
    crashed = Signal(str)


class _Job(QRunnable):
    """بيحضّر التقرير في thread تاني باتصال خاص بيه، فالواجهة متتجمدش."""

    def __init__(self, db_path, key, params):
        super().__init__()
        self.db_path, self.key, self.params = db_path, key, params
        self.signals = _Signals()

    def run(self):
        try:
            self.signals.done.emit(reports.run_report(self.db_path, self.key, self.params))
        except ValidationError as e:
            self.signals.invalid.emit(str(e))
        except Exception:
            self.signals.crashed.emit(traceback.format_exc())


class ReportsCenterPage(QWidget):
    def __init__(self, conn):
        super().__init__()
        self.conn, self.report, self._job = conn, None, None
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 12, 18, 12)
        v.setSpacing(10)

        top = card()
        g = QGridLayout(top)
        g.setContentsMargins(16, 12, 16, 12)
        g.setHorizontalSpacing(12)
        self.kind = QComboBox()
        for key, title, _p in reports.REPORTS:
            self.kind.addItem(title, key)
        g.addWidget(field_label("التقرير"), 0, 0)
        g.addWidget(self.kind, 0, 1, 1, 5)
        self.wh = QComboBox()
        self.customer, self.supplier = SearchCombo(placeholder="اكتب اسم العميل"), SearchCombo(placeholder="اكتب اسم المورد")
        self.product = SearchCombo(by_number=True, placeholder="اكتب اسم الصنف أو رقمه")
        self.dfrom, self.dto = QLineEdit(), QLineEdit()
        self.dfrom.setText(treasury.month_start())
        self.dto.setText(treasury.today())
        self.boxes = {}
        for i, (name, label, w) in enumerate((("warehouse", "المخزن", self.wh), ("customer", "العميل", self.customer),
                                               ("supplier", "المورد", self.supplier), ("product", "الصنف", self.product),
                                               ("from", "من تاريخ", self.dfrom), ("to", "إلى تاريخ", self.dto))):
            box = QWidget()
            bl = QVBoxLayout(box)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.addWidget(field_label(label))
            bl.addWidget(w)
            self.boxes[name] = box
            g.addWidget(box, 1, i)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.btn_show = button("عرض", "primary", self.generate)
        row.addWidget(self.btn_show)
        row.addWidget(button("تصدير Excel", "success", self.export_excel))
        row.addWidget(button("تصدير PDF", "success", self.export_pdf))
        row.addWidget(button("طباعة", "", self.print_report))
        row.addWidget(button("عرض PDF", "", self.open_pdf))
        row.addStretch(1)
        g.addLayout(row, 2, 0, 1, 6)
        v.addWidget(top)

        self.title = QLabel("")
        self.title.setStyleSheet("font-size:18px;font-weight:bold")
        self.subtitle = QLabel("")
        self.subtitle.setStyleSheet("color:#64748b")
        self.status = QLabel("")
        self.status.setStyleSheet("color:#2563eb;font-weight:bold")
        for w in (self.title, self.subtitle, self.status):
            v.addWidget(w)
        self.table = make_table(["-"])
        v.addWidget(self.table, 1)
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("font-size:15px;font-weight:bold")
        v.addWidget(self.summary)
        self.kind.currentIndexChanged.connect(self.on_kind)
        self.on_kind()

    def _fill(self, combo, rows, all_text=None):
        cur = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        if all_text:
            combo.addItem(all_text, None)
        for r in rows:
            combo.addItem(r["name"], r["id"])
        i = combo.findData(cur)
        combo.setCurrentIndex(i if i >= 0 else 0)
        combo.blockSignals(False)

    @guard
    def refresh(self):
        self._fill(self.wh, warehouses.list_warehouses(self.conn), "كل المخازن")
        self._fill(self.customer, parties.list_parties(self.conn, "customer"))
        self._fill(self.supplier, parties.list_parties(self.conn, "supplier"))
        self._fill(self.product, products.list_products(self.conn))

    def on_kind(self, *args):
        needs = next(p for k, _t, p in reports.REPORTS if k == self.kind.currentData())
        for name, box in self.boxes.items():
            box.setVisible(name in needs or (name in ("from", "to") and "dates" in needs))

    def collect_params(self):
        return {"warehouse_id": self.wh.currentData(), "customer_id": self.customer.value(),
                "supplier_id": self.supplier.value(), "product_id": self.product.value(),
                "date_from": self.dfrom.text().strip() or None, "date_to": self.dto.text().strip() or None}

    @guard
    def generate(self):
        self.btn_show.setEnabled(False)
        self.status.setText("جاري تجهيز التقرير...")
        job = _Job(db_file(self.conn), self.kind.currentData(), self.collect_params())
        job.signals.done.connect(self.on_done)
        job.signals.invalid.connect(self.on_invalid)
        job.signals.crashed.connect(self.on_crashed)
        self._job = job   # لازم يفضل متخزّن لحد ما يخلص
        QThreadPool.globalInstance().start(job)

    def _idle(self):
        self.btn_show.setEnabled(True)
        self.status.setText("")

    def on_done(self, report):
        self._idle()
        safe_call(self, self.show_report, report)

    def on_invalid(self, msg):
        self._idle()
        QMessageBox.warning(self, "تنبيه", msg)

    def on_crashed(self, tb):
        self._idle()
        report_error(self, tb)

    def show_report(self, report):
        self.report = report
        self.title.setText(report["title"])
        self.subtitle.setText(report["subtitle"])
        cols = report["columns"]
        self.table.setColumnCount(len(cols))
        self.table.setHorizontalHeaderLabels([t for t, _k in cols])
        self.table.setRowCount(len(report["rows"]))
        for r, row in enumerate(report["rows"]):
            low = reports.LOW_TEXT in row
            for c, ((_t, kind), v) in enumerate(zip(cols, row)):
                self.table.setItem(r, c, cell(reports.format_cell(kind, v), bg="#fff1f2" if low else None,
                                              fg="#9f1239" if low else None))
        self.summary.setText("      |      ".join(f"{lbl}: {reports.format_cell(k, v)}" for lbl, k, v in report["summary"]))

    def _save_as(self, ext, label, writer):
        if self.report is None:
            raise ValidationError("اعرض التقرير الأول")
        path, _f = QFileDialog.getSaveFileName(self, "حفظ " + label, export.default_filename(self.report, ext),
                                               f"{label} (*.{ext})")
        if not path:
            return
        if not path.lower().endswith("." + ext):
            path += "." + ext
        try:
            writer(self.report, path)
        except OSError as e:
            raise ValidationError(f"مقدرتش أحفظ الملف: {e}")
        QMessageBox.information(self, "تم", f"تم حفظ الملف:\n{path}")

    @guard
    def export_excel(self):
        self._save_as("xlsx", "Excel", export.to_excel)

    @guard
    def export_pdf(self):
        self._save_as("pdf", "PDF", printing.export_pdf)

    @guard
    def print_report(self):
        if self.report is None:
            raise ValidationError("اعرض التقرير الأول")
        printing.print_report(self, self.report)

    @guard
    def open_pdf(self):
        if self.report is None:
            raise ValidationError("اعرض التقرير الأول")
        printing.open_report_pdf(self, self.report)


class ReportsTab(QWidget):
    def __init__(self, conn):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        self.inner = QTabWidget()
        self.dashboard, self.center = DashboardPage(conn), ReportsCenterPage(conn)
        self.inner.addTab(self.dashboard, "ملخص")
        self.inner.addTab(self.center, "التقارير")
        v.addWidget(self.inner)
        self.inner.currentChanged.connect(self.refresh)
        self.center.refresh()

    def refresh(self, *_):
        self.inner.currentWidget().refresh()
