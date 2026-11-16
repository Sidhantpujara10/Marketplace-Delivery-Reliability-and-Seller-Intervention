"""Step 2. Build the marts and prove the joins did not fan out or lose value."""
import pathlib, sqlite3, time

ROOT = pathlib.Path(__file__).resolve().parents[1]
con = sqlite3.connect(ROOT / "data" / "olist.db")
one = lambda sql: con.execute(sql).fetchone()

t = time.time()
con.execute("CREATE INDEX IF NOT EXISTS ix_items_order ON stg_order_items (order_id)")
con.executescript((ROOT / "sql" / "01_marts.sql").read_text())
print(f"marts built in {time.time() - t:.1f}s")

checks = {
    "mart_orders has one row per order":
        one("SELECT COUNT(*) = COUNT(DISTINCT order_id) FROM mart_orders")[0],
    "item value in the mart equals item value in staging for the same orders":
        one("""SELECT ABS((SELECT SUM(item_value) FROM mart_orders) -
                          (SELECT SUM(price) FROM stg_order_items
                           WHERE order_id IN (SELECT order_id FROM mart_orders))) < 0.01""")[0],
    "payment value is not double counted":
        one("""SELECT ABS((SELECT SUM(m.order_value) FROM mart_orders m JOIN int_order_payments p USING (order_id)) -
                          (SELECT SUM(payment_value) FROM stg_payments
                           WHERE order_id IN (SELECT order_id FROM mart_orders))) < 0.01""")[0],
    "seller mart order counts add up to the order mart":
        one("SELECT (SELECT SUM(orders) FROM mart_sellers) = (SELECT COUNT(*) FROM mart_orders)")[0],
    "late causes add up to late orders":
        one("SELECT SUM(late_cause != 'on_time') = SUM(is_late) FROM mart_orders")[0],
    "no negative durations":
        one("SELECT MIN(dispatch_days) >= 0 AND MIN(transit_days) >= 0 FROM mart_orders")[0],
    "every order has a seller state and a customer state":
        one("SELECT SUM(seller_state IS NULL OR customer_state IS NULL) = 0 FROM mart_orders")[0],
}
for name, ok in checks.items():
    print(("PASS  " if ok else "FAIL  ") + name)
assert all(checks.values()), "validation failed"

delivered = one("SELECT COUNT(*) FROM stg_orders WHERE order_status = 'delivered'")[0]
kept = one("SELECT COUNT(*) FROM mart_orders")[0]
print(f"delivered orders in source: {delivered:,} | kept in mart: {kept:,} | excluded: {delivered - kept:,}")
