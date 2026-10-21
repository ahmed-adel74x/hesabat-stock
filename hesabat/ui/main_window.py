from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtWidgets import QApplication, QTabWidget, QVBoxLayout, QWidget

from .. import __version__
from ..logic import preferences
from .common import button, guard
from .invoices_tab import InvoicesTab
from .parties_tab import PartiesTab
from .products_tab import ProductsTab
from .reports_tab import ReportsTab
from .stock_ops_tab import StockOpsTab
from .theme import apply_theme
from .treasury_tab import TreasuryTab
from .warehouses_tab import WarehousesTab


class MainWindow(QWidget):
    def __init__(self, conn):
        super().__init__()
        self.setWindowTitle(f"برنامج حسابات البضاعة - {__version__}")
        self.resize(1200, 680)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.conn = conn
        self.theme = preferences.get_theme(conn)
        self.theme_btn = button("", "theme", self.toggle_theme)
        self._update_theme_button()
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs)
        # زرار الثيم جنب تابات الصفحات (في الركن، من غير ما ياخد ارتفاع زيادة)
        self._corner = Qt.Corner.TopLeftCorner
        self.tabs.setCornerWidget(self.theme_btn, self._corner)
        self.theme_btn.show()
        self._corner_checked = False
        self.pages = []
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
            self.pages.append(w)
        self.tabs.currentChanged.connect(self.on_tab)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._corner_checked:
            self._corner_checked = True
            QTimer.singleShot(0, self._ensure_button_on_left)

    def _ensure_button_on_left(self):
        """الركن "الشمال" في Qt ممكن يتعكس في الواجهة العربية (RTL). فبنتأكد من مكان الزرار الفعلي ونبدّله لو طلع يمين."""
        x = self.theme_btn.mapTo(self, QPoint(0, 0)).x() + self.theme_btn.width() / 2
        if x > self.width() / 2:
            other = (Qt.Corner.TopRightCorner if self._corner == Qt.Corner.TopLeftCorner
                     else Qt.Corner.TopLeftCorner)
            self.tabs.setCornerWidget(None, self._corner)
            self._corner = other
            self.tabs.setCornerWidget(self.theme_btn, other)
            self.theme_btn.show()

    def _update_theme_button(self):
        self.theme_btn.setText("☀️ الوضع الفاتح" if self.theme == "dark" else "🌙 الوضع الداكن")

    @guard
    def toggle_theme(self):
        self.theme = "light" if self.theme == "dark" else "dark"
        apply_theme(QApplication.instance(), self.theme)
        preferences.set_theme(self.conn, self.theme)
        self._update_theme_button()

    @guard
    def on_tab(self):
        self.tabs.currentWidget().refresh()   # كل تبويب بيحدّث بياناته لما تفتحه
