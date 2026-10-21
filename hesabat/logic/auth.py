"""تسجيل دخول الأدمن. الاسم وكلمة السر بتتخزن في app_settings (كلمة السر مشفّرة PBKDF2 مع salt، مش نص عادي).
أول مرة: الأدمن الافتراضي marko / 12345، وبعد كده بيغيّره المستخدم من صفحة الإعدادات."""
import hashlib
import hmac
import os

from ..db.connection import tx
from .errors import ValidationError

DEFAULT_USER = "marko"
DEFAULT_PASSWORD = "12345"
MIN_PASSWORD_LEN = 4
_ITERATIONS = 200_000


def _hash(password, salt_hex):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), _ITERATIONS).hex()


def _get(conn, key):
    row = conn.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
    return row[0] if row else None


def _put(conn, key, value):
    conn.execute("INSERT INTO app_settings(key,value) VALUES(?,?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


def _store(conn, username, password):
    salt = os.urandom(16).hex()
    _put(conn, "admin_user", username)
    _put(conn, "admin_salt", salt)
    _put(conn, "admin_hash", _hash(password, salt))


def ensure_admin(conn):
    """بتنشئ الأدمن الافتراضي لو مفيش (قاعدة جديدة أو قديمة قبل إضافة تسجيل الدخول)."""
    if _get(conn, "admin_hash") is None or _get(conn, "admin_user") is None:
        with tx(conn):
            _store(conn, DEFAULT_USER, DEFAULT_PASSWORD)


def admin_name(conn):
    ensure_admin(conn)
    return _get(conn, "admin_user")


def verify(conn, username, password):
    """True لو الاسم وكلمة السر صح. الاسم من غير حساسية لحالة الحروف، وكلمة السر حساسة."""
    ensure_admin(conn)
    user, salt, stored = _get(conn, "admin_user"), _get(conn, "admin_salt"), _get(conn, "admin_hash")
    ok_user = (username or "").strip().lower() == user.lower()
    ok_pass = hmac.compare_digest(_hash(password or "", salt), stored)
    return ok_user and ok_pass


def change_password(conn, old_password, new_password, confirm):
    ensure_admin(conn)
    if not verify(conn, admin_name(conn), old_password):
        raise ValidationError("كلمة السر الحالية غلط")
    if (new_password or "") != (confirm or ""):
        raise ValidationError("كلمة السر الجديدة والتأكيد مش متطابقين")
    if len(new_password or "") < MIN_PASSWORD_LEN:
        raise ValidationError(f"كلمة السر الجديدة لازم تكون {MIN_PASSWORD_LEN} حروف/أرقام على الأقل")
    with tx(conn):
        _store(conn, admin_name(conn), new_password)


def change_name(conn, password, new_name):
    ensure_admin(conn)
    name = (new_name or "").strip()
    if not name:
        raise ValidationError("اكتب اسم الأدمن")
    if not verify(conn, admin_name(conn), password):
        raise ValidationError("كلمة السر الحالية غلط")
    with tx(conn):
        _put(conn, "admin_user", name)
