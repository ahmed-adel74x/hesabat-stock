"""اختبار ذاتي: بيبني قاعدة بيانات مؤقتة، ويشغّل كل الشاشات والتقارير والتصدير (Excel وPDF) من غير ما يظهر شيء.
بيتشغّل على الـ exe بعد ما يتبني (في GitHub Actions) عشان نتأكد إن التغليف سليم:

    HesabatStock.exe --selftest نتيجة.txt        (أو:  python main.py --selftest نتيجة.txt)

بيكتب النتيجة في الملف، وبيخرج بكود 0 لو نجح. بياناتك الحقيقية مبتتلمسش (بيستخدم فولدر مؤقت)."""
import os
import sys
import tempfile
import threading
import traceback

TIMEOUT_SECONDS = 180


def _write(path, lines):
    if path:
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")


def run_selftest(out_path=None, strict_files=True):
    lines, ok = [], True

    def watchdog():  # لو حاجة وقفت (مثلاً نافذة حوار) منعلّقش الـ build
        _write(out_path, lines + ["TIMEOUT: السلف تست علّق"])
        os._exit(2)

    timer = threading.Timer(TIMEOUT_SECONDS, watchdog)
    timer.daemon = True
    timer.start()
    try:
        tmp = tempfile.mkdtemp(prefix="hesabat_selftest_")
        os.environ["HESABAT_DATA_DIR"] = tmp
        if sys.platform != "win32":
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from . import __version__
        from .app import create_app
        from .db.connection import connect, default_db_path
        from .db.migrations import init_db
        from .logic import export, invoices, parties, products, reports
        from .ui import common as ui_common
        from .ui import printing
        from .ui.main_window import MainWindow

        def _raise(parent, tb):                 # أي خطأ في الواجهة = فشل (مفيش نوافذ حوار تعلّق)
            raise RuntimeError("خطأ في الواجهة:\n" + tb)
        ui_common.report_error = _raise

        lines.append(f"hesabat {__version__} | python {sys.version.split()[0]} | frozen={getattr(sys, 'frozen', False)}")
        app = create_app()
        path = default_db_path()
        conn = connect(path)
        init_db(conn, path)
        sup = parties.create(conn, "supplier", "مورد تجريبي", opening_balance="100")
        prod = products.create(conn, "صنف تجريبي", "10", "15", "2", "0")
        invoices.create_invoice(conn, "purchase", sup, 1, [(prod, "10", "10")], "0", "50")
        invoices.create_invoice(conn, "sale", parties.default_customer_id(conn), 1, [(prod, "3", "15")], "0", "45")
        win = MainWindow(conn)
        for page in win.pages:
            page.refresh()
        lines.append(f"الشاشات: {len(win.pages)}")
        params = {"customer_id": parties.default_customer_id(conn), "supplier_id": sup, "product_id": prod}
        for key, title, _p in reports.REPORTS:
            rep = reports.build_report(conn, key, params)
            xlsx, pdf = os.path.join(tmp, f"{key}.xlsx"), os.path.join(tmp, f"{key}.pdf")
            export.to_excel(rep, xlsx)
            printing.export_pdf(rep, pdf)
            if strict_files:
                for f in (xlsx, pdf):
                    if not os.path.exists(f) or os.path.getsize(f) < 500:
                        raise RuntimeError(f"ملف التصدير فاضي أو مش موجود: {f}")
        lines.append(f"التقارير: {len(reports.REPORTS)} (Excel + PDF)")
        lines.append("SELFTEST OK")
    except BaseException:
        ok = False
        lines += [traceback.format_exc(), "SELFTEST FAILED"]
    finally:
        timer.cancel()
        _write(out_path, lines)
    return 0 if ok else 1


SAMPLE_REPORT = {"title": "فحص الطباعة", "subtitle": "تقرير تجريبي", "columns": [("الصنف", "text"), ("الكمية", "qty"), ("السعر", "money")],
                 "rows": [["سكر أبيض", 2500, 1550], ["شاي", 1000, 7000]], "summary": [("الإجمالي", "money", 8550)]}


def run_print_check(out_path=None, strict_files=True, preview_seconds=5.0):
    """بيفحص الطباعة على الجهاز: الطابعات اللي Qt شايفها، وإنشاء PDF، وفتح نافذة المعاينة فعلاً.
    مش بيفشّل البرنامج (معلوماتي): بيكتب النتيجة في الملف.
        HesabatStock.exe --selftest-print نتيجة.txt      (أو:  python main.py --selftest-print نتيجة.txt)"""
    lines, code = [], 0

    def watchdog():
        _write(out_path, lines + ["TIMEOUT: فحص الطباعة علّق"])
        os._exit(2)

    timer = threading.Timer(120, watchdog)
    timer.daemon = True
    timer.start()
    try:
        os.environ["HESABAT_DATA_DIR"] = tempfile.mkdtemp(prefix="hesabat_printcheck_")
        if sys.platform != "win32":
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from .app import create_app
        from .logic import export
        from .ui import printing
        app = create_app()
        lines.append(f"python {sys.version.split()[0]} | frozen={getattr(sys, 'frozen', False)}")
        lines += printing.describe_printers()
        pdf = os.path.join(tempfile.mkdtemp(prefix="hesabat_pdf_"), "check.pdf")
        printing.export_pdf(SAMPLE_REPORT, pdf)
        size = os.path.getsize(pdf) if os.path.exists(pdf) else 0
        if strict_files and size < 500:
            raise RuntimeError(f"إنشاء PDF فشل (الحجم {size})")
        lines.append(f"إنشاء PDF: OK ({size} بايت)")
        painted = printing.check_preview(app, export.report_html(SAMPLE_REPORT), preview_seconds)
        lines.append("نافذة المعاينة: " + ("OK (اترسمت الصفحة)" if painted else "اتفتحت لكن الصفحة ما اترسمتش (تحذير)"))
        lines.append("PRINT CHECK DONE")
    except BaseException:
        code = 1
        lines += [traceback.format_exc(), "PRINT CHECK FAILED"]
    finally:
        timer.cancel()
        _write(out_path, lines)
    return code
