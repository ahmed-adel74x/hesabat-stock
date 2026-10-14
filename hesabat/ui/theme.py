# الستايل الموحد (أبيض)
STYLE = """
* { font-size: 14px; }
QWidget { background:#ffffff; color:#0f172a; }
QTabWidget::pane { border:none; border-top:1px solid #e2e8f0; }
QTabBar::tab { background:#ffffff; color:#64748b; padding:11px 14px; border:none; border-bottom:3px solid transparent; font-weight:bold; }
QTabBar::tab:selected { color:#2563eb; border-bottom:3px solid #2563eb; }
QTabBar::tab:hover { color:#1d4ed8; }
QLineEdit, QComboBox { background:#ffffff; border:1px solid #cbd5e1; border-radius:8px; padding:8px 10px; selection-background-color:#bfdbfe; selection-color:#0f172a; }
QLineEdit:focus, QComboBox:focus { border:1px solid #2563eb; }
QComboBox QAbstractItemView { background:#ffffff; color:#0f172a; border:1px solid #cbd5e1; selection-background-color:#dbeafe; selection-color:#0f172a; }
QComboBox::drop-down { border:none; width:28px; }
QComboBox QLineEdit { border:none; padding:0; background:transparent; }
QListView { background:#ffffff; color:#0f172a; border:1px solid #cbd5e1; selection-background-color:#dbeafe; selection-color:#0f172a; }
QPushButton { background:#f1f5f9; color:#0f172a; border:1px solid #e2e8f0; border-radius:8px; padding:9px 22px; font-weight:bold; }
QPushButton:hover { background:#e2e8f0; }
QPushButton#primary { background:#2563eb; color:#ffffff; border:none; }
QPushButton#primary:hover { background:#1d4ed8; }
QPushButton#success { background:#16a34a; color:#ffffff; border:none; }
QPushButton#success:hover { background:#15803d; }
QPushButton#danger { background:#fee2e2; color:#b91c1c; border:none; }
QPushButton#danger:hover { background:#fecaca; }
QTableWidget { background:#ffffff; alternate-background-color:#f8fafc; border:1px solid #e2e8f0; gridline-color:#eef2f7; selection-background-color:#dbeafe; selection-color:#0f172a; }
QHeaderView::section { background:#f1f5f9; color:#334155; border:none; border-bottom:1px solid #e2e8f0; padding:9px; font-weight:bold; }
QTableCornerButton::section { background:#f1f5f9; border:none; }
QScrollBar:vertical { background:#ffffff; width:10px; margin:0; }
QScrollBar::handle:vertical { background:#cbd5e1; border-radius:5px; min-height:30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
QLabel#field { color:#475569; font-weight:bold; }
QFrame#card { background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; }
QFrame#card QLabel { background:transparent; border:none; }
"""
