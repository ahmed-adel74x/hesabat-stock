"""أدوات مشتركة للواجهة. هنا مفيش SQL ولا منطق عمل."""
import sys
import traceback

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QFrame, QHeaderView, QLabel, QMessageBox,
                               QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)

from ..applog import log
from ..logic.errors import ValidationError

CENTER = Qt.AlignmentFlag.AlignCenter
ROLE = Qt.ItemDataRole.UserRole


def report_error(parent, tb_text):
    """أي خطأ غير متوقع: يتطبع في الترمينال ويظهر في نافذة بنصه الكامل."""
    print(tb_text, file=sys.stderr)
    log(tb_text)
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle("خطأ غير متوقع")
    box.setText("حصل خطأ غير متوقع. اضغط Show Details وانسخ النص كله وابعته للمطور.")
    box.setDetailedText(tb_text)
    box.exec()


def guard(fn):
    """بتلف معالج الأحداث: ValidationError يظهر كتنبيه عادي، وأي خطأ تاني بنصه الكامل."""
    def wrapper(self, *args):
        try:
            return fn(self)
        except ValidationError as e:
            QMessageBox.warning(self, "تنبيه", str(e))
        except Exception:
            report_error(self, traceback.format_exc())
    wrapper.__name__ = fn.__name__
    return wrapper


def safe_call(parent, fn, *args):
    """نفس فكرة guard بس لدوال بتاخد معاملات."""
    try:
        return fn(*args)
    except ValidationError as e:
        QMessageBox.warning(parent, "تنبيه", str(e))
    except Exception:
        report_error(parent, traceback.format_exc())


def make_table(headers):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    t.setAlternatingRowColors(True)
    t.setShowGrid(False)
    t.verticalHeader().setVisible(False)
    t.verticalHeader().setDefaultSectionSize(38)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    return t


def cell(text, data=None, bg=None, fg=None, editable=False):
    it = QTableWidgetItem(str(text))
    it.setTextAlignment(CENTER)
    if data is not None:
        it.setData(ROLE, data)
    if bg:
        from PySide6.QtGui import QColor
        it.setBackground(QColor(bg))
    if fg:
        from PySide6.QtGui import QColor
        it.setForeground(QColor(fg))
    if not editable:
        it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return it


def selected_id(table):
    items = table.selectedItems()
    return table.item(items[0].row(), 0).data(ROLE) if items else None


def field_label(text):
    l = QLabel(text)
    l.setObjectName("field")
    return l


def card():
    f = QFrame()
    f.setObjectName("card")
    return f


def button(text, kind="", slot=None):
    b = QPushButton(text)
    if kind:
        b.setObjectName(kind)
    if slot:
        b.clicked.connect(slot)
    return b


def confirm(parent, text):
    return QMessageBox.question(parent, "تأكيد", text) == QMessageBox.StandardButton.Yes


def fill_combo(combo, rows, id_key="id", name_key="name"):
    cur = combo.currentData()
    combo.blockSignals(True)
    combo.clear()
    for r in rows:
        combo.addItem(r[name_key], r[id_key])
    i = combo.findData(cur)
    if combo.count():
        combo.setCurrentIndex(i if i >= 0 else 0)
    combo.blockSignals(False)


def show_text(parent, title, text):
    d = QDialog(parent)
    d.setWindowTitle(title)
    d.resize(700, 460)
    v = QVBoxLayout(d)
    box = QPlainTextEdit(text)
    box.setReadOnly(True)
    box.setStyleSheet("border:1px solid #64748b;border-radius:8px;padding:8px;")
    v.addWidget(box)
    v.addWidget(button("تمام", "primary", d.accept))
    d.exec()


def stat_card(title, color):
    """كارت رقم صغير. بيرجع (الإطار، الـ QLabel اللي فيه القيمة)."""
    f = card()
    l = QVBoxLayout(f)
    l.setContentsMargins(16, 12, 16, 12)
    t = QLabel(title)
    t.setStyleSheet("color:#64748b;font-size:13px")
    v = QLabel("0")
    v.setStyleSheet(f"color:{color};font-size:24px;font-weight:bold")
    l.addWidget(t)
    l.addWidget(v)
    return f, v
