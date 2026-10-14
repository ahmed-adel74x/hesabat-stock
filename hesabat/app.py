import sys
import traceback

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from .db.connection import connect, default_db_path
from .db.migrations import MigrationError, init_db
from .ui.common import report_error, show_text
from .ui.main_window import MainWindow
from .ui.theme import STYLE


def run():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

    def hook(t, v, tb):
        report_error(None, "".join(traceback.format_exception(t, v, tb)))
    sys.excepthook = hook

    path = default_db_path()
    conn = connect(path)
    try:
        report = init_db(conn, path)
    except MigrationError as e:
        text = e.report["text"] if e.report else str(e)
        print(text, file=sys.stderr)
        QMessageBox.critical(None, "فشل ترحيل البيانات",
                             "البيانات القديمة لم تتغير (تم التراجع). انسخ التقرير وابعته للمطور:\n\n" + text)
        return 1
    win = MainWindow(conn)
    win.show()
    if report:
        print(report["text"])
        show_text(win, "تقرير ترحيل البيانات", report["text"])
    code = app.exec()
    conn.close()
    return code
