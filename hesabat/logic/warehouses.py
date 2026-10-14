import sqlite3

from ..db.connection import tx
from .errors import ValidationError
from . import inventory


def list_warehouses(conn):
    return conn.execute("SELECT * FROM warehouses WHERE active=1 ORDER BY id").fetchall()


def main_id(conn):
    return conn.execute("SELECT MIN(id) FROM warehouses WHERE active=1").fetchone()[0]


def _name(name):
    n = (name or "").strip()
    if not n:
        raise ValidationError("اكتب اسم المخزن")
    return n


def create(conn, name, location="", notes=""):
    with tx(conn):
        try:
            return conn.execute("INSERT INTO warehouses(name,location,notes,created_at) VALUES(?,?,?,?)",
                                (_name(name), location.strip(), notes.strip(), inventory.now_str())).lastrowid
        except sqlite3.IntegrityError:
            raise ValidationError("اسم المخزن موجود بالفعل (ممكن يكون محذوف سابقاً)")


def update(conn, wid, name, location="", notes=""):
    with tx(conn):
        inventory.get_warehouse(conn, wid)
        try:
            conn.execute("UPDATE warehouses SET name=?, location=?, notes=? WHERE id=?",
                         (_name(name), location.strip(), notes.strip(), wid))
        except sqlite3.IntegrityError:
            raise ValidationError("اسم المخزن موجود بالفعل (ممكن يكون محذوف سابقاً)")


def deactivate(conn, wid):
    with tx(conn):
        inventory.get_warehouse(conn, wid)
        if len(list_warehouses(conn)) <= 1:
            raise ValidationError("لازم يفضل مخزن واحد على الأقل")
        left = conn.execute("""SELECT COUNT(*) FROM (SELECT product_id FROM stock_movements WHERE warehouse_id=?
                               GROUP BY product_id HAVING SUM(qty_m)<>0)""", (wid,)).fetchone()[0]
        if left:
            raise ValidationError("المخزن فيه أرصدة. حوّلها لمخزن تاني الأول.")
        conn.execute("UPDATE warehouses SET active=0 WHERE id=?", (wid,))
