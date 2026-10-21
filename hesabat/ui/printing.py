"""معاينة وطباعة وتصدير PDF. نص الفاتورة/التقرير نفسه جاي من logic (invoice_html / report_html).

ملاحظات مهمة (أخطاء حصلت قبل كده):
  - نافذة المعاينة بتستخدم QPrinter طول ما هي مفتوحة، فلازم نحتفظ بالطابعة في متغير. لو اتعملت جوه نداء
    الإنشاء مباشرة Python بيمسحها والنافذة بتشاور على حاجة اتمسحت (معاينة فاضية أو قفل البرنامج).
  - مقاس الصفحة (A4) والهوامش بنحددهم بنفسنا، فالمعاينة متعتمدش على وجود طابعة مثبّتة على الجهاز.
  - لو المعاينة فشلت لأي سبب بنفتح الملف كـ PDF في برنامج العرض ومنه تطبع (Ctrl+P)."""
import os
import tempfile
import time
import traceback

from PySide6.QtCore import QMarginsF, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPageLayout, QPageSize, QTextDocument
from PySide6.QtPrintSupport import QPrintPreviewDialog, QPrinter, QPrinterInfo
from PySide6.QtWidgets import QMessageBox

from ..applog import log
from ..logic import export, invoices
from ..logic.errors import ValidationError


def _document(html):
    doc = QTextDocument()
    opt = doc.defaultTextOption()
    opt.setTextDirection(Qt.LayoutDirection.RightToLeft)
    doc.setDefaultTextOption(opt)
    # الورقة بيضا دايماً: من غيره الكلام بياخد لون الثيم (فاتح في الدارك) فيختفي على الورق
    doc.setDefaultStyleSheet("body, p, td, th, h1, h2, h3, b, span { color:#000000; }")
    doc.setHtml(html)
    return doc


def _try(label, fn, *args):
    """إعدادات اختيارية للطابعة: لو فشلت منوقّفش الطباعة بسببها، بنسجّلها بس."""
    try:
        fn(*args)
    except Exception:
        log(f"printing: {label} failed\n" + traceback.format_exc())


def _printer(landscape, pdf_path=None):
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    _try("page size", printer.setPageSize, QPageSize(QPageSize.PageSizeId.A4))
    _try("margins", printer.setPageMargins, QMarginsF(12, 12, 12, 12), QPageLayout.Unit.Millimeter)
    if landscape:
        _try("orientation", printer.setPageOrientation, QPageLayout.Orientation.Landscape)
    if pdf_path:
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(pdf_path)
    return printer


def _print_doc(doc, printer):
    fn = getattr(doc, "print_", None) or getattr(doc, "print")   # الاسم بيختلف بين إصدارات PySide6
    fn(printer)


def _wide(report):
    return len(report["columns"]) > 5      # الجدول العريض بيتطبع بالعرض


def _preview(parent, doc, landscape=False):
    printer = _printer(landscape)           # لازم يفضل متخزّن في متغير طول ما النافذة مفتوحة
    dlg = QPrintPreviewDialog(printer, parent)
    dlg._keep = (printer, doc)              # ونربطه بالنافذة نفسها كمان

    def paint(p):                           # أي خطأ في رسم الصفحة كان بيختفي من غير ما نعرف
        try:
            _print_doc(doc, p)
        except Exception:
            log("printing: paint failed\n" + traceback.format_exc())
    dlg.paintRequested.connect(paint)
    dlg.resize(900, 700)
    dlg.exec()


def _write_pdf(doc, path, landscape=False):
    printer = _printer(landscape, path)
    _print_doc(doc, printer)


def _open_pdf(doc, landscape, name):
    """بيكتب PDF مؤقت ويفتحه في برنامج العرض الافتراضي (ومنه المستخدم يطبع)."""
    fd, path = tempfile.mkstemp(prefix=f"hesabat_{name}_", suffix=".pdf")
    os.close(fd)
    _write_pdf(doc, path, landscape)
    if not QDesktopServices.openUrl(QUrl.fromLocalFile(path)):
        raise ValidationError(f"مقدرتش أفتح ملف الـ PDF تلقائياً. الملف محفوظ هنا وتقدر تفتحه بإيدك:\n{path}")
    return path


def _print_html(parent, html, landscape=False, name="document"):
    doc = _document(html)
    try:
        _preview(parent, doc, landscape)
    except Exception:
        log("printing: preview failed\n" + traceback.format_exc())
        _open_pdf(doc, landscape, name)
        QMessageBox.information(parent, "طباعة", "نافذة معاينة الطباعة ما اشتغلتش على الجهاز ده، فاتفتح الملف "
                                                 "كـ PDF. اطبعه من برنامج العرض (Ctrl+P).")


def print_html(parent, html, landscape=False, name="document"):
    """طباعة/معاينة أي نص HTML جاهز (كشوف الحساب مثلاً)."""
    _print_html(parent, html, landscape, name)


def print_invoice(parent, conn, invoice_id):
    _print_html(parent, invoices.invoice_html(conn, invoice_id), False, "invoice")


def print_report(parent, report):
    _print_html(parent, export.report_html(report), _wide(report), "report")


def open_invoice_pdf(parent, conn, invoice_id):
    return _open_pdf(_document(invoices.invoice_html(conn, invoice_id)), False, "invoice")


def open_report_pdf(parent, report):
    return _open_pdf(_document(export.report_html(report)), _wide(report), "report")


def export_pdf(report, path):
    _write_pdf(_document(export.report_html(report)), path, _wide(report))


# ---------------------------------------------------------------- تشخيص (python main.py --selftest-print)
def describe_printers():
    try:
        names = list(QPrinterInfo.availablePrinterNames())
        default = QPrinterInfo.defaultPrinterName()
        return [f"الطابعات اللي Qt شايفها: {', '.join(names) if names else 'لا يوجد'}",
                f"الطابعة الافتراضية: {default or 'لا يوجد'}"]
    except Exception:
        return ["تعذّر قراءة قائمة الطابعات:\n" + traceback.format_exc()]


def check_preview(app, html, seconds=5.0):
    """بيفتح نافذة المعاينة فعلاً ويستنى لحد ما ترسم الصفحة. بيرجع True لو اترسمت."""
    doc, painted = _document(html), []
    printer = _printer(False)
    dlg = QPrintPreviewDialog(printer, None)
    dlg._keep = (printer, doc)

    def paint(p):
        painted.append(1)
        _print_doc(doc, p)
    dlg.paintRequested.connect(paint)
    dlg.show()
    deadline = time.time() + seconds
    while not painted and time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)
    dlg.close()
    return bool(painted)
