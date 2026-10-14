"""معاينة وطباعة وتصدير PDF. نص الفاتورة/التقرير نفسه جاي من logic (invoice_html / report_html)."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QPageLayout, QTextDocument
from PySide6.QtPrintSupport import QPrintPreviewDialog, QPrinter

from ..logic import export, invoices


def _document(html):
    doc = QTextDocument()
    opt = doc.defaultTextOption()
    opt.setTextDirection(Qt.LayoutDirection.RightToLeft)
    doc.setDefaultTextOption(opt)
    doc.setHtml(html)
    return doc


def _printer(landscape):
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    if landscape:
        printer.setPageOrientation(QPageLayout.Orientation.Landscape)
    return printer


def _preview(parent, doc, landscape=False):
    dlg = QPrintPreviewDialog(_printer(landscape), parent)
    dlg.paintRequested.connect(doc.print_)
    dlg.resize(900, 700)
    dlg.exec()


def print_invoice(parent, conn, invoice_id):
    _preview(parent, _document(invoices.invoice_html(conn, invoice_id)))


def print_report(parent, report):
    _preview(parent, _document(export.report_html(report)), len(report["columns"]) > 5)


def export_pdf(report, path):
    printer = _printer(len(report["columns"]) > 5)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(path)
    _document(export.report_html(report)).print_(printer)
