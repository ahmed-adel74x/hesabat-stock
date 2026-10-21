"""
تمثيل الأرقام:
  - المبالغ بالقروش (int)   : 12.50 جنيه = 1250   (اسم الحقل بينتهي بـ _c)
  - الكميات بالألف (int)    : 2.5 كجم   = 2500    (اسم الحقل بينتهي بـ _m)
بكده مفيش float في أي حساب مالي أو مخزني.
"""
import re
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from .errors import ValidationError

_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩٫", "0123456789.")
_NUM_RE = re.compile(r"[+-]?(\d+(\.\d*)?|\.\d+)")
_MAX_ABS = 10 ** 13


def _dec(x):
    if isinstance(x, (int, float, Decimal)):
        return Decimal(str(x))
    s = str(x).strip().translate(_AR_DIGITS).replace(",", ".")
    if not _NUM_RE.fullmatch(s):
        raise ValueError("not a number")
    return Decimal(s)


def _round(d):
    return int(d.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def to_cents(x):
    return _round(_dec(x) * 100)


def to_milli(x):
    return _round(_dec(x) * 1000)


def mul_qty_price(qty_m, price_c):
    """كمية (بالألف) × سعر (بالقروش) = مبلغ بالقروش، بتقريب نصف لفوق."""
    return _round(Decimal(qty_m) * Decimal(price_c) / 1000)


def milli_cents_to_cents(x):
    return _round(Decimal(x) / 1000)


def parse_money(text, field="المبلغ", allow_negative=False, allow_empty=False):
    s = "" if text is None else str(text).strip()
    if s == "":
        if allow_empty:
            return 0
        raise ValidationError(f"{field}: اكتب قيمة")
    try:
        c = to_cents(s)
    except (ValueError, InvalidOperation):
        raise ValidationError(f"{field}: رقم غير صحيح")
    if abs(c) > _MAX_ABS:
        raise ValidationError(f"{field}: الرقم كبير جداً")
    if c < 0 and not allow_negative:
        raise ValidationError(f"{field}: لا يمكن أن يكون سالباً")
    return c


def parse_qty(text, field="الكمية", allow_zero=False, allow_empty=False):
    s = "" if text is None else str(text).strip()
    if s == "":
        if allow_empty:
            return 0
        raise ValidationError(f"{field}: اكتب قيمة")
    try:
        m = to_milli(s)
    except (ValueError, InvalidOperation):
        raise ValidationError(f"{field}: رقم غير صحيح")
    if m > _MAX_ABS:
        raise ValidationError(f"{field}: الرقم كبير جداً")
    if m < 0:
        raise ValidationError(f"{field}: لا يمكن أن تكون سالبة")
    if m == 0 and not allow_zero:
        raise ValidationError(f"{field}: لازم تكون أكبر من صفر")
    return m


def _drop_zero_cents(s):
    """2,000.00 -> 2,000 (لو فيه قروش فعلاً زي 12.50 بتفضل زي ما هي)."""
    return s[:-3] if s.endswith(".00") else s


def fmt_money(c):
    return _drop_zero_cents(f"{Decimal(c) / 100:,.2f}")


def fmt_qty(m):
    s = f"{Decimal(m) / 1000:,.3f}".rstrip("0").rstrip(".")
    return s or "0"


def plain_money(c):
    return _drop_zero_cents(f"{Decimal(c) / 100:.2f}")


def plain_qty(m):
    s = f"{Decimal(m) / 1000:.3f}".rstrip("0").rstrip(".")
    return s or "0"
