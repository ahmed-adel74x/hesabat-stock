from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from .common import guard
from .invoices_tab import InvoicesTab
from .parties_tab import PartiesTab
from .products_tab import ProductsTab
from .reports_tab import ReportsTab
from .stock_ops_tab import StockOpsTab
from .treasury_tab import TreasuryTab
from .warehouses_tab import WarehousesTab


class MainWindow(QWidget):
    def __init__(self, conn):
        super().__init__()
        self.setWindowTitle("برنامج حسابات البضاعة")
        self.resize(1200, 680)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs)
        for w, title in ((ProductsTab(conn), "الأصناف"),
                         (InvoicesTab(conn, "sale"), "المبيعات"),
                         (InvoicesTab(conn, "sale_return"), "مرتجع مبيعات"),
                         (InvoicesTab(conn, "purchase"), "المشتريات"),
                         (InvoicesTab(conn, "purchase_return"), "مرتجع مشتريات"),
                         (PartiesTab(conn, "customer"), "العملاء"),
                         (PartiesTab(conn, "supplier"), "الموردين"),
                         (TreasuryTab(conn), "الخزينة"),
                         (WarehousesTab(conn), "المخازن"),
                         (StockOpsTab(conn), "تحويل وجرد"),
                         (ReportsTab(conn), "التقارير")):
            self.tabs.addTab(w, title)
        self.tabs.currentChanged.connect(self.on_tab)

    @guard
    def on_tab(self):
        self.tabs.currentWidget().refresh()   # كل تبويب بيحدّث بياناته لما تفتحه
