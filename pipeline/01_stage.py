"""Step 1. Stage each raw Olist file as its own table. No joins, no cleaning beyond types.

Raw files: github.com/olist/work-at-olist-data (the original publisher, Olist).
"""
import csv, pathlib, sqlite3, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
BASE = "https://raw.githubusercontent.com/olist/work-at-olist-data/master/datasets/"
FILES = {  # staged table -> source file
    "stg_orders": "olist_orders_dataset.csv",
    "stg_order_items": "olist_order_items_dataset.csv",
    "stg_sellers": "olist_sellers_dataset.csv",
    "stg_payments": "olist_order_payments_dataset.csv",
    "stg_customers": "olist_customers_dataset.csv",
    "stg_reviews": "olist_order_reviews_dataset.csv",
    "stg_products": "olist_products_dataset.csv",
    "stg_category_names": "product_category_name_translation.csv",
}
NUMERIC = {"price", "freight_value", "payment_value", "payment_installments", "payment_sequential",
           "review_score", "order_item_id"}


def download():
    import urllib.request
    RAW.mkdir(parents=True, exist_ok=True)
    for f in FILES.values():
        if not (RAW / f).exists():
            urllib.request.urlretrieve(BASE + f, RAW / f)


def stage(con):
    for table, f in FILES.items():
        with open(RAW / f, newline="", encoding="utf-8-sig") as fh:
            rows = csv.reader(fh)
            cols = next(rows)
            types = ["REAL" if c in NUMERIC else "TEXT" for c in cols]
            con.execute(f"DROP TABLE IF EXISTS {table}")
            con.execute(f"CREATE TABLE {table} ({', '.join(f'{c} {t}' for c, t in zip(cols, types))})")
            data = [[(v if v != "" else None) for v in r] for r in rows]
            con.executemany(f"INSERT INTO {table} VALUES ({','.join('?' * len(cols))})", data)
        print(f"{table:20s} {len(data):>7,} rows")
    con.commit()


if __name__ == "__main__":
    download()
    db = ROOT / "data" / "olist.db"
    db.unlink(missing_ok=True)
    stage(sqlite3.connect(db))
