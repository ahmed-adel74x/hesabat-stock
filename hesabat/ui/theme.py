"""الستايل الموحد: فاتح ودارك. الألوان في قاموس لكل وضع، والـ STYLE بيتبني منها."""

LIGHT = dict(
    bg="#ffffff", text="#0f172a", muted="#64748b", border="#e2e8f0", input_border="#cbd5e1",
    tab_text="#64748b", tab_active="#2563eb", tab_hover="#1d4ed8", accent="#2563eb",
    select="#dbeafe", input_select="#bfdbfe", btn="#f1f5f9", btn_hover="#e2e8f0",
    primary="#2563eb", primary_hover="#1d4ed8", success="#16a34a", success_hover="#15803d",
    danger_bg="#fee2e2", danger_text="#b91c1c", danger_hover="#fecaca",
    alt_row="#f8fafc", grid="#eef2f7", header_bg="#f1f5f9", header_text="#334155",
    handle="#cbd5e1", label="#475569",
)

DARK = dict(
    bg="#0f172a", text="#e2e8f0", muted="#94a3b8", border="#334155", input_border="#475569",
    tab_text="#94a3b8", tab_active="#60a5fa", tab_hover="#93c5fd", accent="#60a5fa",
    select="#1e3a8a", input_select="#1d4ed8", btn="#1e293b", btn_hover="#334155",
    primary="#2563eb", primary_hover="#3b82f6", success="#16a34a", success_hover="#22c55e",
    danger_bg="#450a0a", danger_text="#fca5a5", danger_hover="#7f1d1d",
    alt_row="#162033", grid="#1e293b", header_bg="#1e293b", header_text="#cbd5e1",
    handle="#475569", label="#cbd5e1",
)

PALETTES = {"light": LIGHT, "dark": DARK}

_TEMPLATE = """
* { font-size: 14px; }
QWidget { background:%(bg)s; color:%(text)s; }
QTabWidget::pane { border:none; border-top:1px solid %(border)s; }
QTabBar::tab { background:%(bg)s; color:%(tab_text)s; padding:11px 14px; border:none; border-bottom:3px solid transparent; font-weight:bold; }
QTabBar::tab:selected { color:%(tab_active)s; border-bottom:3px solid %(tab_active)s; }
QTabBar::tab:hover { color:%(tab_hover)s; }
QLineEdit, QComboBox { background:%(bg)s; border:1px solid %(input_border)s; border-radius:8px; padding:8px 10px; selection-background-color:%(input_select)s; selection-color:%(text)s; }
QLineEdit:focus, QComboBox:focus { border:1px solid %(accent)s; }
QComboBox QAbstractItemView { background:%(bg)s; color:%(text)s; border:1px solid %(input_border)s; selection-background-color:%(select)s; selection-color:%(text)s; }
QComboBox::drop-down { border:none; width:28px; }
QComboBox QLineEdit { border:none; padding:0; background:transparent; }
QListView { background:%(bg)s; color:%(text)s; border:1px solid %(input_border)s; selection-background-color:%(select)s; selection-color:%(text)s; }
QPushButton { background:%(btn)s; color:%(text)s; border:1px solid %(border)s; border-radius:8px; padding:9px 22px; font-weight:bold; }
QPushButton:hover { background:%(btn_hover)s; }
QPushButton#primary { background:%(primary)s; color:#ffffff; border:none; }
QPushButton#primary:hover { background:%(primary_hover)s; }
QPushButton#success { background:%(success)s; color:#ffffff; border:none; }
QPushButton#success:hover { background:%(success_hover)s; }
QPushButton#danger { background:%(danger_bg)s; color:%(danger_text)s; border:none; }
QPushButton#danger:hover { background:%(danger_hover)s; }
QPushButton#theme { padding:6px 14px; }
QTableWidget { background:%(bg)s; alternate-background-color:%(alt_row)s; border:1px solid %(border)s; gridline-color:%(grid)s; selection-background-color:%(select)s; selection-color:%(text)s; }
QHeaderView::section { background:%(header_bg)s; color:%(header_text)s; border:none; border-bottom:1px solid %(border)s; padding:9px; font-weight:bold; }
QTableCornerButton::section { background:%(header_bg)s; border:none; }
QScrollBar:vertical { background:%(bg)s; width:10px; margin:0; }
QScrollBar::handle:vertical { background:%(handle)s; border-radius:5px; min-height:30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
QLabel#field { color:%(label)s; font-weight:bold; }
QFrame#card { background:%(bg)s; border:1px solid %(border)s; border-radius:12px; }
QFrame#card QLabel { background:transparent; border:none; }
QMessageBox, QDialog { background:%(bg)s; }
"""


def build_style(mode):
    return _TEMPLATE % PALETTES.get(mode, LIGHT)


STYLE = build_style("light")     # الافتراضي (فاتح)


def apply_theme(app, mode):
    app.setStyleSheet(build_style(mode))
