"""سجل أخطاء في ملف (error.log جوه فولدر البيانات). مهم لأن البرنامج المثبّت بيشتغل من غير نافذة سوداء."""
import os
from datetime import datetime

from .db.connection import data_dir

MAX_BYTES = 1_000_000


def log_path():
    return os.path.join(data_dir(), "error.log")


def log(text):
    """بيضيف نص للسجل. مبيرميش أي خطأ أبداً (السجل مينفعش يوقّع البرنامج)."""
    try:
        path = log_path()
        if os.path.exists(path) and os.path.getsize(path) > MAX_BYTES:
            os.replace(path, path + ".old")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}]\n{text}\n")
    except Exception:
        pass
