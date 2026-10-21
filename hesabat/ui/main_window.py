from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from .. import __version__
from ..logic import invoices
from .common import guard
from .invoices_tab import InvoicesTab
from .parties_tab import PartiesTab
from .products_tab import ProductsTab
from .reports_tab import ReportsTab
from .settings_tab import SettingsTab
from .stock_ops_tab import StockOpsTab
from .treasury_tab import TreasuryTab
from .warehouses_tab import WarehousesTab


class MainWindow(QWidget):
    def __init__(self, conn):
        super().__init__()
        self.setWindowTitle(f"برنامج حسابات البضاعة - {__version__}")
        self.resize(1200, 680)
        self.logout_requested = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.conn = conn
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs)
        self.pages = []
        self.invoice_tabs = {}          # نوع الفاتورة -> تبويبها (عشان نفتح فاتورة للتعديل من أي مكان)
        for kind in ("sale", "sale_return", "purchase", "purchase_return"):
            self.invoice_tabs[kind] = InvoicesTab(conn, kind)
        for w, title in ((ProductsTab(conn), "الأصناف"),
                         (self.invoice_tabs["sale"], "المبيعات"),
                         (self.invoice_tabs["sale_return"], "مرتجع مبيعات"),
                         (self.invoice_tabs["purchase"], "المشتريات"),
                         (self.invoice_tabs["purchase_return"], "مرتجع مشتريات"),
                         (PartiesTab(conn, "customer"), "العملاء"),
                         (PartiesTab(conn, "supplier"), "الموردين"),
                         (TreasuryTab(conn), "الخزينة"),
                         (WarehousesTab(conn), "المخازن"),
                         (StockOpsTab(conn), "تحويل وجرد"),
                         (ReportsTab(conn), "التقارير"),
                         (SettingsTab(conn, self.logout), "الإعدادات")):
            self.tabs.addTab(w, title)
            self.pages.append(w)
        self.tabs.currentChanged.connect(self.on_tab)

    def logout(self):
        """بيقفل النافذة الرئيسية، وapp.run بيرجّع شاشة الدخول."""
        self.logout_requested = True
        self.close()

    def edit_invoice(self, invoice_id):
        """بيروح لتبويب الفاتورة المناسب ويفتحها للتعديل (بتتنادي من كشف حساب العميل/المورد)."""
        kind = invoices.get_invoice(self.conn, invoice_id)["invoice"]["kind"]
        tab = self.invoice_tabs[kind]
        self.tabs.setCurrentWidget(tab)
        tab.open_invoice(invoice_id)

    def invoice_deleted(self, invoice_id):
        """بعد مسح فاتورة من أي مكان: أي شاشة فاتورة كانت فاتحاها للتعديل بتتفرّغ، وباقي الشاشات بتتحدّث."""
        for tab in self.invoice_tabs.values():
            if tab.editor.edit_id == invoice_id:
                tab.editor.new_invoice()
        self.tabs.currentWidget().refresh()

    @guard
    def on_tab(self):
        self.tabs.currentWidget().refresh()   # كل تبويب بيحدّث بياناته لما تفتحه
