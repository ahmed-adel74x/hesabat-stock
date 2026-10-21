import ctypes
import os
import sys
import traceback

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from .db.connection import connect, default_db_path
from .db.migrations import MigrationError, init_db
from .ui.common import report_error, show_text
from .ui.main_window import MainWindow
from .ui.theme import apply_theme


def resource_path(rel):
    """مسار ملف مرفق (أيقونة). شغال من الكود المصدري ومن الـ exe (PyInstaller)."""
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


def create_app():
    if sys.platform == "win32":
        try:  # عشان أيقونة البرنامج تظهر صح في شريط المهام
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("HesabatStock.App")
        except Exception:
            pass
    app = QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    icon = resource_path(os.path.join("hesabat", "assets", "icon.png"))
    if os.path.exists(icon):
        app.setWindowIcon(QIcon(icon))
    return app


def run(argv=None):
    argv = list(argv or [])
    if argv and argv[0] == "--selftest":          # اختبار ذاتي من غير واجهة (بيستخدمه الـ build)
        from .selftest import run_selftest
        return run_selftest(argv[1] if len(argv) > 1 else None)

    if argv and argv[0] == "--selftest-print":    # تشخيص الطباعة على الجهاز ده
        from .selftest import run_print_check
        return run_print_check(argv[1] if len(argv) > 1 else None)

    app = create_app()

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
    from .logic import preferences
    apply_theme(app, preferences.get_theme(conn))
    win = MainWindow(conn)
    win.show()
    if report:
        print(report["text"])
        show_text(win, "تقرير ترحيل البيانات", report["text"])
    code = app.exec()
    conn.close()
    return code
