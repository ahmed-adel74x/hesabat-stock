"""
تجربة الترحيل على نسخة من بياناتك الحقيقية من غير ما الأصل يتلمس:

    python3 tools/test_migration.py ~/HesabatStock/stock.db      (أو أي نسخة من stock.db القديم)

بتطبع تقرير المطابقة (عدد الأصناف، مجموع الأرصدة، القيم، المبيعات...) قبل وبعد.
اعتمد الترحيل الحقيقي بس لما التقرير يقول "متطابق ✔".
"""
import os, shutil, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hesabat.db.connection import connect
from hesabat.db.migrations import init_db, MigrationError


def main():
    if len(sys.argv) != 2 or not os.path.isfile(sys.argv[1]):
        print(__doc__); return 2
    work = os.path.join(tempfile.mkdtemp(), "stock.db")
    shutil.copy(sys.argv[1], work)                       # بنشتغل على نسخة مؤقتة بس
    conn = connect(work)
    try:
        rep = init_db(conn, work)
    except MigrationError as e:
        print(e.report["text"] if e.report else e); print("\nفشل الترحيل. الأصل لم يتغير."); return 1
    if rep is None:
        print("القاعدة دي محوّلة بالفعل للهيكل الجديد (أو جديدة)."); return 0
    print(rep["text"])
    print("\nintegrity_check:", conn.execute("PRAGMA integrity_check").fetchone()[0])
    print("foreign_key_check:", conn.execute("PRAGMA foreign_key_check").fetchall() or "سليم")
    print("\nالملف الأصلي لم يتغير:", sys.argv[1])
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
