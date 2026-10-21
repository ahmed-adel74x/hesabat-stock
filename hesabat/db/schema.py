SCHEMA_VERSION = 4

# كل جملة لوحدها (executescript بيعمل COMMIT ضمني فمنستخدمهوش جوه transaction)
V1_STATEMENTS = [
"""CREATE TABLE warehouses(
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    location TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL)""",
"""CREATE TABLE products(
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    sell_price_c INTEGER NOT NULL DEFAULT 0 CHECK(sell_price_c >= 0),
    buy_price_c  INTEGER NOT NULL DEFAULT 0 CHECK(buy_price_c  >= 0),
    avg_cost_c   INTEGER NOT NULL DEFAULT 0 CHECK(avg_cost_c   >= 0),
    min_qty_m    INTEGER NOT NULL DEFAULT 0 CHECK(min_qty_m    >= 0),
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL)""",
"""CREATE TABLE suppliers(
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    phone TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    opening_balance_c INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL)""",
"""CREATE TABLE customers(
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    phone TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    opening_balance_c INTEGER NOT NULL DEFAULT 0,
    is_default INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL)""",
# مصدر الحقيقة لأي رصيد: الرصيد = مجموع qty_m (موجب دخول، سالب خروج)
"""CREATE TABLE stock_movements(
    id INTEGER PRIMARY KEY,
    product_id   INTEGER NOT NULL REFERENCES products(id),
    warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
    kind TEXT NOT NULL CHECK(kind IN ('opening','purchase','sale','purchase_return',
         'sale_return','transfer_in','transfer_out','adjust')),
    qty_m INTEGER NOT NULL CHECK(qty_m <> 0),
    unit_price_c INTEGER NOT NULL DEFAULT 0,
    unit_cost_c  INTEGER NOT NULL DEFAULT 0,
    ref_type TEXT, ref_id INTEGER,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL)""",
"CREATE INDEX ix_mov_pw        ON stock_movements(product_id, warehouse_id)",
"CREATE INDEX ix_mov_date      ON stock_movements(created_at)",
"CREATE INDEX ix_mov_kind_date ON stock_movements(kind, created_at)",
"CREATE INDEX ix_mov_ref       ON stock_movements(ref_type, ref_id)",
# amount_c موجب = بيزوّد الرصيد المستحق، سالب = بينقصه
"""CREATE TABLE party_ledger(
    id INTEGER PRIMARY KEY,
    party_type TEXT NOT NULL CHECK(party_type IN ('customer','supplier')),
    party_id INTEGER NOT NULL,
    entry_type TEXT NOT NULL CHECK(entry_type IN ('invoice','payment','return','adjust')),
    amount_c INTEGER NOT NULL,
    ref_type TEXT, ref_id INTEGER,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL)""",
"CREATE INDEX ix_ledger_party ON party_ledger(party_type, party_id, created_at)",
"""CREATE TABLE stock_transfers(
    id INTEGER PRIMARY KEY,
    from_wh INTEGER NOT NULL REFERENCES warehouses(id),
    to_wh   INTEGER NOT NULL REFERENCES warehouses(id),
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    CHECK(from_wh <> to_wh))""",
"""CREATE TABLE stocktakes(
    id INTEGER PRIMARY KEY,
    warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL)""",
"""CREATE TABLE stocktake_items(
    id INTEGER PRIMARY KEY,
    stocktake_id INTEGER NOT NULL REFERENCES stocktakes(id),
    product_id   INTEGER NOT NULL REFERENCES products(id),
    system_qty_m  INTEGER NOT NULL,
    counted_qty_m INTEGER NOT NULL,
    diff_qty_m    INTEGER NOT NULL)""",
"CREATE INDEX ix_stitems ON stocktake_items(stocktake_id)",
]


# ---------------- النسخة 2: الخزينة ----------------
V2_STATEMENTS = [
"""CREATE TABLE app_settings(key TEXT PRIMARY KEY, value TEXT NOT NULL)""",
"INSERT INTO app_settings(key,value) VALUES('treasury_opening_c','0')",
# المبلغ دايماً موجب، والاتجاه من kind (قبض = داخل، صرف = خارج)
"""CREATE TABLE treasury_entries(
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK(kind IN ('receipt','payment')),
    amount_c INTEGER NOT NULL CHECK(amount_c > 0),
    party_type TEXT CHECK(party_type IN ('customer','supplier')),
    party_id INTEGER,
    category TEXT NOT NULL DEFAULT '',          -- بيان المصروف/الإيراد العام
    ref_type TEXT, ref_id INTEGER,              -- voucher | invoice | closing
    note TEXT NOT NULL DEFAULT '',
    entry_date TEXT NOT NULL,                   -- تاريخ السند المحاسبي YYYY-MM-DD
    voided INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    CHECK((party_type IS NULL) = (party_id IS NULL)))""",
"CREATE INDEX ix_tr_date  ON treasury_entries(entry_date, id)",
"CREATE INDEX ix_tr_party ON treasury_entries(party_type, party_id)",
"CREATE INDEX ix_tr_ref   ON treasury_entries(ref_type, ref_id)",
"""CREATE TABLE treasury_closings(
    id INTEGER PRIMARY KEY,
    close_date TEXT NOT NULL UNIQUE,
    opening_c  INTEGER NOT NULL,
    receipts_c INTEGER NOT NULL,
    payments_c INTEGER NOT NULL,
    closing_c  INTEGER NOT NULL,
    counted_c  INTEGER,                         -- النقدية الفعلية اللي اتعدّت (اختياري)
    diff_c     INTEGER NOT NULL DEFAULT 0,      -- الفعلي - الدفتري
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL)""",
]


# ---------------- النسخة 3: الفواتير (شراء / مرتجع شراء، وبيع / مرتجع بيع في المرحلة 4) ----------------
V3_STATEMENTS = [
"""CREATE TABLE invoices(
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK(kind IN ('purchase','purchase_return','sale','sale_return')),
    number INTEGER NOT NULL,                       -- ترقيم متسلسل لكل نوع
    party_type TEXT NOT NULL CHECK(party_type IN ('customer','supplier')),
    party_id INTEGER NOT NULL,
    warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
    invoice_date TEXT NOT NULL,
    subtotal_c INTEGER NOT NULL CHECK(subtotal_c >= 0),
    discount_c INTEGER NOT NULL DEFAULT 0 CHECK(discount_c >= 0),
    total_c    INTEGER NOT NULL CHECK(total_c >= 0),
    paid_c     INTEGER NOT NULL DEFAULT 0 CHECK(paid_c >= 0),   -- المدفوع (أو المستلم نقداً في المرتجع)
    note TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','cancelled')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(kind, number),
    CHECK(discount_c <= subtotal_c),
    CHECK(paid_c <= total_c))""",
"""CREATE TABLE invoice_items(
    id INTEGER PRIMARY KEY,
    invoice_id INTEGER NOT NULL REFERENCES invoices(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    qty_m INTEGER NOT NULL CHECK(qty_m > 0),
    unit_price_c  INTEGER NOT NULL CHECK(unit_price_c >= 0),
    line_total_c  INTEGER NOT NULL CHECK(line_total_c >= 0))""",
"CREATE INDEX ix_inv_kind_date ON invoices(kind, invoice_date)",
"CREATE INDEX ix_inv_party     ON invoices(party_type, party_id)",
"CREATE INDEX ix_invitems_inv  ON invoice_items(invoice_id)",
"CREATE INDEX ix_invitems_prod ON invoice_items(product_id)",
]

# رقم النسخة الجديدة -> جمل إنشائها. الترقية بتمشي خطوة خطوة.
# النسخة 4: مسح الفواتير الملغية القديمة (مبقاش فيه فاتورة بتفضل ظاهرة كـ«ملغية»). الخطوة ممكن تكون جملة SQL أو دالة.
from .maintenance import purge_cancelled_invoices  # noqa: E402

UPGRADE_STEPS = {2: V2_STATEMENTS, 3: V3_STATEMENTS, 4: [purge_cancelled_invoices]}
