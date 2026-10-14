"""بحث نصي بسيط يناسب العربي: بيتجاهل التشكيل والفروق الشائعة (أ/ا/إ، ة/ه، ى/ي) والأرقام العربية."""
import re

_TASHKEEL = re.compile("[\u064B-\u0652\u0670]")
_DIGITS = "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹"
_MAP = str.maketrans({**{c: str(i % 10) for i, c in enumerate(_DIGITS)},
                      "أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه", "ـ": ""})


def normalize(text):
    return _TASHKEEL.sub("", str(text or "")).translate(_MAP).lower().strip()


def matches(query, name, number=None):
    """كل كلمة في البحث لازم تكون جزء من الاسم، أو تكون رقم الصنف نفسه. بحث فاضي = الكل."""
    tokens = normalize(query).split()
    n = normalize(name)
    for tok in tokens:
        if tok in n or (number is not None and tok.isdigit() and tok == str(number)):
            continue
        return False
    return True


def first_match(query, items):
    """items: قائمة (اسم، رقم). بترجع ترتيب أول عنصر مطابق، أو None (لو مفيش أو البحث فاضي)."""
    if not normalize(query):
        return None
    for i, (name, number) in enumerate(items):
        if matches(query, name, number):
            return i
    return None
