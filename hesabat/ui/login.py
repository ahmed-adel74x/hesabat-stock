"""شاشة تسجيل الدخول اللي بتظهر أول ما البرنامج يفتح (وبعد تسجيل الخروج)."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QDialog, QLabel, QLineEdit, QVBoxLayout

from .. import __version__
from ..logic import auth
from .common import button, card, field_label, guard

MAX_TRIES = 5


class LoginDialog(QDialog):
    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn, self.tries = conn, 0
        self.setWindowTitle("تسجيل الدخول")
        self.setMinimumSize(440, 560)
        self.resize(440, 560)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(30, 26, 30, 26)
        outer.setSpacing(14)
        icon = QLabel("📦")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("font-size:52px")
        title = QLabel("برنامج حسابات البضاعة")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size:21px;font-weight:bold")
        sub = QLabel("سجّل دخولك للمتابعة")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet("color:#64748b")
        outer.addWidget(icon)
        outer.addWidget(title)
        outer.addWidget(sub)

        box = card()
        v = QVBoxLayout(box)
        v.setContentsMargins(20, 16, 20, 16)
        v.setSpacing(8)
        self.user, self.password = QLineEdit(), QLineEdit()
        self.user.setPlaceholderText("اسم المستخدم")
        self.password.setPlaceholderText("كلمة السر")
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        for e in (self.user, self.password):
            e.setMinimumHeight(44)
            e.setStyleSheet("font-size:16px;padding:6px 10px;")
        self.show_pw = QCheckBox("إظهار كلمة السر")
        self.show_pw.toggled.connect(self.toggle_show)
        for w in (field_label("اسم المستخدم"), self.user, field_label("كلمة السر"), self.password, self.show_pw):
            v.addWidget(w)
        self.user.returnPressed.connect(self.password.setFocus)
        self.password.returnPressed.connect(self.login)
        outer.addWidget(box)
        self.msg = QLabel("")
        self.msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.msg.setStyleSheet("color:#b91c1c;font-weight:bold")
        outer.addWidget(self.msg)
        outer.addWidget(button("دخول", "primary", self.login))
        ver = QLabel(f"الإصدار {__version__}")
        ver.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ver.setStyleSheet("color:#94a3b8;font-size:12px")
        outer.addWidget(ver)
        outer.addStretch(1)
        self.user.setFocus()

    def toggle_show(self, on):
        self.password.setEchoMode(QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password)

    @guard
    def login(self):
        if auth.verify(self.conn, self.user.text(), self.password.text()):
            self.accept()
            return
        self.tries += 1
        self.password.clear()
        left = MAX_TRIES - self.tries
        if left <= 0:
            self.reject()          # بعد 5 محاولات غلط البرنامج بيقفل
            return
        self.msg.setText("اسم المستخدم أو كلمة السر غلط")
        self.password.setFocus()
