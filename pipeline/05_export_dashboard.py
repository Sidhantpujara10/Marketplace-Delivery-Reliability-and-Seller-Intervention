"""Step 5. Export a compact, column oriented data file for the dashboard (one entry per order)."""
import json, pathlib, sqlite3
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
con = sqlite3.connect(ROOT / "data" / "olist.db")
o = pd.read_sql("SELECT * FROM mart_orders ORDER BY purchase_date", con)
R = json.loads((ROOT / "data" / "results.json").read_text())

top_cat = o.category.value_counts().index[:14]
o["cat"] = o.category.where(o.category.isin(top_cat), "other").str.replace("_", " ")

def codes(col):
    c = pd.Categorical(o[col]); return list(c.categories), c.codes.tolist()

months, m = codes("purchase_month")
sstates, ss = codes("seller_state")
cstates, cs = codes("customer_state")
cats, ct = codes("cat")
sel = pd.Categorical(o.seller_id)
meta = o.groupby("seller_id")[["seller_city", "seller_state"]].first().loc[sel.categories]
sellers = [[f"S-{sid[:5].upper()}", city.title(), st] for sid, (city, st) in zip(meta.index, meta.values)]

payload = {
    "months": months, "sellerStates": sstates, "customerStates": cstates, "categories": cats, "sellers": sellers,
    "m": m, "s": sel.codes.tolist(), "ss": ss, "cs": cs, "c": ct,
    "cause": o.late_cause.map({"on_time": 0, "dispatch": 1, "transit": 2}).tolist(),
    "dm": o.dispatch_late.astype(int).tolist(),
    "x": o.excess_days.astype(int).tolist(),
    "v": o.order_value.round().astype(int).tolist(),
    "d": (o.dispatch_days * 10).round().astype(int).tolist(),      # dispatch time in tenths of a day
    "results": R,
}
out = ROOT / "data" / "dashboard_data.js"
out.write_text("window.OLIST=" + json.dumps(payload, separators=(",", ":")) + ";\n")
print(f"exported {len(o):,} orders, {out.stat().st_size / 1e6:.2f} MB")
