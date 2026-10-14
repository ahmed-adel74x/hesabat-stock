import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime


def data_dir():
    d = os.path.join(os.path.expanduser("~"), "HesabatStock")
    os.makedirs(d, exist_ok=True)
    return d


def default_db_path():
    return os.path.join(data_dir(), "stock.db")


def backups_dir(db_path):
    d = os.path.join(os.path.dirname(os.path.abspath(db_path)), "backups")
    os.makedirs(d, exist_ok=True)
    return d


def connect(path):
    # autocommit: الـ transactions بنفتحها ونقفلها بإيدينا عن طريق tx()
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def tx(conn):
    """transaction واحدة: commit لو كله تمام، rollback عند أي خطأ.
    لو اتنادت جوه transaction تانية بتنضم ليها (والـ rollback بيتعمل من الخارجية)."""
    if conn.in_transaction:
        yield
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def backup_db(conn, db_path, label):
    dest_path = os.path.join(backups_dir(db_path), f"stock_{label}_{datetime.now():%Y%m%d_%H%M%S}.db")
    dest = sqlite3.connect(dest_path)
    try:
        conn.backup(dest)
    finally:
        dest.close()
    return dest_path


def db_file(conn):
    """مسار ملف قاعدة البيانات (عشان الشغل في thread تاني بيفتح اتصال خاص بيه)."""
    return conn.execute("PRAGMA database_list").fetchone()[2]
