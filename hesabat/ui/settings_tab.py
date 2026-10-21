"""صفحة الإعدادات: بيانات الأدمن، تغيير كلمة السر، تسجيل الخروج، وتغيير الثيم (فاتح/داكن)."""
from PySide6.QtWidgets import QApplication, QCheckBox, QGridLayout, QLabel, QLineEdit, QMessageBox, QVBoxLayout, QWidget

from ..logic import auth, preferences
from .common import button, card, confirm, field_label, guard
from .theme import apply_theme


def _pw_edit(placeholder):
    e = QLineEdit()
    e.setEchoMode(QLineEdit.EchoMode.Password)
    e.setPlaceholderText(placeholder)
    return e


class SettingsTab(QWidget):
    def __init__(self, conn, on_logout):
        super().__init__()
        self.conn, self.on_logout = conn, on_logout
        self.theme = preferences.get_theme(conn)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(14)

        # --- الحساب
        acc = card()
        g = QGridLayout(acc)
        g.setContentsMargins(18, 14, 18, 14)
        g.setHorizontalSpacing(12)
        head = QLabel("حساب الأدمن")
        head.setStyleSheet("font-size:16px;font-weight:bold")
        g.addWidget(head, 0, 0, 1, 3)
        self.name = QLineEdit()
        self.name_pw = _pw_edit("كلمة السر الحالية (للتأكيد)")
        g.addWidget(field_label("اسم الأدمن"), 1, 0)
        g.addWidget(field_label("كلمة السر الحالية"), 1, 1)
        g.addWidget(self.name, 2, 0)
        g.addWidget(self.name_pw, 2, 1)
        g.addWidget(button("حفظ الاسم", "primary", self.save_name), 2, 2)
        g.setColumnStretch(0, 2)
        g.setColumnStretch(1, 2)
        v.addWidget(acc)

        # --- كلمة السر
        pw = card()
        p = QGridLayout(pw)
        p.setContentsMargins(18, 14, 18, 14)
        p.setHorizontalSpacing(12)
        head = QLabel("تغيير كلمة السر")
        head.setStyleSheet("font-size:16px;font-weight:bold")
        p.addWidget(head, 0, 0, 1, 4)
        self.old, self.new, self.confirm_pw = _pw_edit("الحالية"), _pw_edit("الجديدة"), _pw_edit("أعد كتابة الجديدة")
        for i, (t, w) in enumerate((("كلمة السر الحالية", self.old), ("كلمة السر الجديدة", self.new),
                                    ("تأكيد الجديدة", self.confirm_pw))):
            p.addWidget(field_label(t), 1, i)
            p.addWidget(w, 2, i)
        p.addWidget(button("تغيير كلمة السر", "primary", self.save_password), 2, 3)
        self.show_pw = QCheckBox("إظهار كلمة السر")
        self.show_pw.toggled.connect(self.toggle_show)
        p.addWidget(self.show_pw, 3, 0, 1, 2)
        v.addWidget(pw)

        # --- المظهر
        look = card()
        l = QGridLayout(look)
        l.setContentsMargins(18, 14, 18, 14)
        head = QLabel("المظهر")
        head.setStyleSheet("font-size:16px;font-weight:bold")
        l.addWidget(head, 0, 0)
        self.theme_btn = button("", "theme", self.toggle_theme)
        l.addWidget(self.theme_btn, 0, 1)
        l.setColumnStretch(2, 1)
        v.addWidget(look)

        # --- الخروج
        out = card()
        o = QGridLayout(out)
        o.setContentsMargins(18, 14, 18, 14)
        head = QLabel("الجلسة")
        head.setStyleSheet("font-size:16px;font-weight:bold")
        o.addWidget(head, 0, 0)
        o.addWidget(button("تسجيل الخروج", "danger", self.logout), 0, 1)
        o.setColumnStretch(2, 1)
        v.addWidget(out)
        v.addStretch(1)
        self._update_theme_button()
        self.refresh()

    @guard
    def refresh(self):
        self.name.setText(auth.admin_name(self.conn))

    def _update_theme_button(self):
        self.theme_btn.setText("☀️ التحويل للوضع الفاتح" if self.theme == "dark" else "🌙 التحويل للوضع الداكن")

    @guard
    def toggle_theme(self):
        self.theme = "light" if self.theme == "dark" else "dark"
        apply_theme(QApplication.instance(), self.theme)
        preferences.set_theme(self.conn, self.theme)
        self._update_theme_button()

    def toggle_show(self, on):
        mode = QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password
        for e in (self.old, self.new, self.confirm_pw, self.name_pw):
            e.setEchoMode(mode)

    @guard
    def save_name(self):
        auth.change_name(self.conn, self.name_pw.text(), self.name.text())
        self.name_pw.clear()
        self.refresh()
        QMessageBox.information(self, "تم", "تم تغيير اسم الأدمن ✔")

    @guard
    def save_password(self):
        auth.change_password(self.conn, self.old.text(), self.new.text(), self.confirm_pw.text())
        for e in (self.old, self.new, self.confirm_pw):
            e.clear()
        QMessageBox.information(self, "تم", "تم تغيير كلمة السر ✔\nاستخدم الجديدة في المرة الجاية.")

    @guard
    def logout(self):
        if confirm(self, "تسجيل الخروج؟"):
            self.on_logout()
