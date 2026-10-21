"""عمليات صيانة بالـ SQL الخام، مشتركة بين ترقية القاعدة ومسح الفواتير. بتشتغل جوه transaction بتفتحها الدالة اللي بتناديها."""


def purge_invoice(conn, invoice_id):
    """بيمسح فاتورة (ملغية) وكل أثرها من القاعدة: بنودها وحركات المخزون وقيود حساب الطرف وسندات الخزينة المرتبطة بيها.

    مبيمسحش غير لو أثر الفاتورة متعادل فعلاً (صافي كل صنف/مخزن = صفر، وصافي كل طرف = صفر، ومفيش سند خزينة شغّال)،
    فالمسح مبيغيّرش أي رصيد. بيرجع True لو اتمسحت، False لو الأثر مش متعادل (ومبيلمسش حاجة)."""
    entries = [r[0] for r in conn.execute("SELECT id FROM treasury_entries WHERE ref_type='invoice' AND ref_id=?",
                                          (invoice_id,))]
    marks = ",".join("?" * len(entries)) or "NULL"
    ledger_where = (f"(ref_type='invoice' AND ref_id=?) OR "
                    f"(ref_type IN ('treasury','treasury_void') AND ref_id IN ({marks}))")
    args = [invoice_id] + entries
    unbalanced_ledger = conn.execute(
        f"SELECT 1 FROM party_ledger WHERE {ledger_where} GROUP BY party_type, party_id "
        "HAVING SUM(amount_c) <> 0 LIMIT 1", args).fetchone()
    unbalanced_stock = conn.execute(
        "SELECT 1 FROM stock_movements WHERE ref_type='invoice' AND ref_id=? GROUP BY product_id, warehouse_id "
        "HAVING SUM(qty_m) <> 0 LIMIT 1", (invoice_id,)).fetchone()
    live_cash = conn.execute("SELECT 1 FROM treasury_entries WHERE ref_type='invoice' AND ref_id=? AND voided=0 LIMIT 1",
                             (invoice_id,)).fetchone()
    if unbalanced_ledger or unbalanced_stock or live_cash:
        return False
    conn.execute(f"DELETE FROM party_ledger WHERE {ledger_where}", args)
    conn.execute("DELETE FROM treasury_entries WHERE ref_type='invoice' AND ref_id=?", (invoice_id,))
    conn.execute("DELETE FROM stock_movements WHERE ref_type='invoice' AND ref_id=?", (invoice_id,))
    conn.execute("DELETE FROM invoice_items WHERE invoice_id=?", (invoice_id,))
    conn.execute("DELETE FROM invoices WHERE id=?", (invoice_id,))
    return True


def purge_cancelled_invoices(conn):
    """خطوة ترقية النسخة 4: بتمسح الفواتير الملغية القديمة (اللي أثرها متعادل بس). بترجع عدد اللي اتمسح."""
    ids = [r[0] for r in conn.execute("SELECT id FROM invoices WHERE status='cancelled'")]
    return sum(1 for i in ids if purge_invoice(conn, i))
