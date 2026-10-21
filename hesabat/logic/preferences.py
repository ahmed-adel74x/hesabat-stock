"""تفضيلات المستخدم (زي وضع العرض فاتح/دارك). بتتخزن في جدول app_settings."""
from ..db.connection import tx

THEMES = ("light", "dark")


def get_theme(conn):
    row = conn.execute("SELECT value FROM app_settings WHERE key='theme'").fetchone()
    return row[0] if row and row[0] in THEMES else "light"


def set_theme(conn, mode):
    if mode not in THEMES:
        raise ValueError(mode)
    with tx(conn):
        conn.execute("INSERT INTO app_settings(key,value) VALUES('theme',?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (mode,))
