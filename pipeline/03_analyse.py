"""Step 3. SQL analysis, mix decomposition, bootstrap intervals, holdout test, pilot simulation, query plans."""
import json, pathlib, sqlite3, time
import numpy as np, pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
con = sqlite3.connect(ROOT / "data" / "olist.db")
rng = np.random.default_rng(42)
R = {}                                         # everything the report, workbook and dashboard need
MIN_ORDERS = 30                                # minimum volume before a seller is judged
PEAK = ["2017-11", "2018-02", "2018-03"]       # months where the late rate spiked


def sql_report():
    out = {}
    for block in (ROOT / "sql" / "02_analysis.sql").read_text().split("\n\n"):
        lines = block.splitlines()
        title = next((l[3:] for l in lines if l.startswith("-- ") and l[3:4].isdigit()), None)
        q = "\n".join(l for l in lines if not l.startswith("--")).strip()
        if not title or not q:
            continue
        df = pd.read_sql(q, con)
        print(f"\n== {title}\n{df.to_string(index=False)}")
        out[title.split(".")[0]] = df.to_dict("records")
    return out


def wilson(k, n, z=1.96):
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def kitagawa(df, dim):
    """Split the change in late rate between two periods into a mix effect and a rate effect."""
    a = df[~df.peak].groupby(dim).is_late.agg(["mean", "size"])
    b = df[df.peak].groupby(dim).is_late.agg(["mean", "size"])
    g = a.join(b, how="outer", lsuffix="_a", rsuffix="_b")
    g[["size_a", "size_b"]] = g[["size_a", "size_b"]].fillna(0)
    wa, wb = g.size_a / g.size_a.sum(), g.size_b / g.size_b.sum()
    ra, rb = g.mean_a.fillna(g.mean_b), g.mean_b.fillna(g.mean_a)   # a group absent in one period has no rate change
    mix = ((wb - wa) * (ra + rb) / 2).sum()
    rate = ((rb - ra) * (wa + wb) / 2).sum()
    return round(100 * mix, 2), round(100 * rate, 2)


R["sql"] = sql_report()
o = pd.read_sql("SELECT * FROM mart_orders", con)
o["peak"] = o.purchase_month.isin(PEAK)
platform = o.is_late.mean()

# ---- 1. mix against rate: do seller, lane or category mix explain the spikes? ----
base, peak = o[~o.peak].is_late.mean(), o[o.peak].is_late.mean()
R["decomposition"] = {"baseline_rate": round(100 * base, 2), "peak_rate": round(100 * peak, 2),
                      "change_pts": round(100 * (peak - base), 2), "by": {}}
for dim, label in [("category", "Category mix"), ("lane", "Lane mix"), ("seller_id", "Seller mix")]:
    mix, rate = kitagawa(o, dim)
    R["decomposition"]["by"][label] = {"mix_pts": mix, "rate_pts": rate}
cause = o.groupby("peak").apply(lambda d: pd.Series({
    "dispatch": 100 * (d.late_cause == "dispatch").mean(), "transit": 100 * (d.late_cause == "transit").mean()}))
R["decomposition"]["cause_pts"] = {"dispatch": round(cause.loc[True, "dispatch"] - cause.loc[False, "dispatch"], 2),
                                   "transit": round(cause.loc[True, "transit"] - cause.loc[False, "transit"], 2)}
print("\n== Mix against rate (percentage points)\n", json.dumps(R["decomposition"], indent=1))

# ---- 2. bootstrap intervals (resample orders, 2,000 draws; the top seller set is fixed before resampling) ----
late = o.is_late.to_numpy()
by_seller = o.groupby("seller_id").is_late.agg(["sum", "size"]).sort_values("sum", ascending=False)
top = max(1, round(0.05 * len(by_seller)))
in_top = o.seller_id.isin(by_seller.index[:top]).to_numpy()
boot_rate, boot_late_share, boot_order_share = [], [], []
for _ in range(2000):
    idx = rng.integers(0, len(o), len(o))
    l, t = late[idx], in_top[idx]
    boot_rate.append(l.mean()); boot_late_share.append((l * t).sum() / l.sum()); boot_order_share.append(t.mean())
ci = lambda x: [round(100 * float(v), 2) for v in np.percentile(x, [2.5, 97.5])]
R["bootstrap"] = {"late_rate": round(100 * platform, 2), "late_rate_ci": ci(boot_rate),
                  "top5pct_sellers": int(top),
                  "top5pct_share_of_late": round(100 * (late * in_top).sum() / late.sum(), 2),
                  "top5pct_share_of_late_ci": ci(boot_late_share),
                  "top5pct_share_of_orders": round(100 * in_top.mean(), 2),
                  "top5pct_share_of_orders_ci": ci(boot_order_share)}
print("\n== Bootstrap 95% intervals\n", json.dumps(R["bootstrap"], indent=1))

# ---- 3. flag sellers fairly: minimum volume, an interval, and an expected rate for where and when they ship ----
# A seller shipping to Rio in March 2018 will look bad whatever they do. Expected late rate for an order is the
# platform late rate for its month and destination state. A seller is flagged only if the lower bound of their
# own late rate is above what their order mix predicts.
def score(df, min_orders=MIN_ORDERS):
    cell = df.groupby(["purchase_month", "customer_state"]).is_late.transform("mean")
    g = df.assign(exp=cell).groupby("seller_id").agg(
        orders=("is_late", "size"), late=("is_late", "sum"), expected=("exp", "sum"),
        late_dispatch=("late_cause", lambda x: (x == "dispatch").sum()),
        late_transit=("late_cause", lambda x: (x == "transit").sum()),
        dispatch_miss=("dispatch_late", "sum"))
    g["lo"], g["hi"] = wilson(g.late, g.orders)
    g["dm_lo"], _ = wilson(g.dispatch_miss, g.orders)
    g["eligible"] = g.orders >= min_orders
    g["flag_naive"] = g.eligible & (g.lo > df.is_late.mean())
    g["flag_adjusted"] = g.eligible & (g.lo > g.expected / g.orders)
    g["flag_dispatch"] = g.eligible & (g.dm_lo > df.dispatch_late.mean())
    g["excess_late"] = (g.late - g.expected).round(1)
    return g

sc = score(o)
s = pd.read_sql("SELECT * FROM mart_sellers", con).set_index("seller_id").join(
    sc[["expected", "lo", "hi", "eligible", "flag_naive", "flag_adjusted", "flag_dispatch", "excess_late"]])
s["expected_rate"] = (100 * s.expected / s.orders).round(2)
s["main_cause"] = np.where(s.late_dispatch >= s.late_transit, "dispatch", "transit")
share = lambda m, col: round(100 * s.loc[m, col].sum() / s[col].sum(), 1)
R["flagging"] = {"min_orders": MIN_ORDERS, "sellers": len(s), "eligible": int(s.eligible.sum()),
                 "below_min_with_rate_25plus": int(((~s.eligible) & (s.late_rate >= 25)).sum()),
                 "naive": {"flagged": int(s.flag_naive.sum()), "orders_pct": share(s.flag_naive, "orders"),
                           "late_pct": share(s.flag_naive, "late_orders")},
                 "adjusted": {"flagged": int(s.flag_adjusted.sum()), "orders_pct": share(s.flag_adjusted, "orders"),
                              "late_pct": share(s.flag_adjusted, "late_orders")},
                 "dispatch": {"flagged": int(s.flag_dispatch.sum()), "orders_pct": share(s.flag_dispatch, "orders"),
                              "late_pct": share(s.flag_dispatch, "late_orders"),
                              "dispatch_late_pct": share(s.flag_dispatch, "late_dispatch")},
                 "naive_cleared_by_adjustment": int((s.flag_naive & ~s.flag_adjusted).sum())}
print("\n== Flagging\n", json.dumps(R["flagging"], indent=1))

# ---- 4. holdout: do flagged sellers stay bad? Flag on data to Feb 2018, judge on Apr to Aug 2018 ----
train, test = o[o.purchase_month <= "2018-02"], o[o.purchase_month >= "2018-04"]   # March 2018 spike left out
tr, te_cell = score(train), test.assign(exp=test.groupby(["purchase_month", "customer_state"]).is_late.transform("mean"))
R["holdout"] = {}
for name, col, metric in [("naive late rate flag", "flag_naive", "is_late"),
                          ("adjusted late rate flag", "flag_adjusted", "is_late"),
                          ("dispatch miss flag", "flag_dispatch", "dispatch_late")]:
    ids = tr.index[tr[col]]
    a, b = train[train.seller_id.isin(ids)], test[test.seller_id.isin(ids)]
    rest_a, rest_b = train[~train.seller_id.isin(ids)], test[~test.seller_id.isin(ids)]
    gap_a = a[metric].mean() - rest_a[metric].mean()
    gap_b = b[metric].mean() - rest_b[metric].mean()
    R["holdout"][name] = {"metric": metric, "sellers_flagged": len(ids), "still_active": int(b.seller_id.nunique()),
                          "train_flagged": round(100 * a[metric].mean(), 2), "train_others": round(100 * rest_a[metric].mean(), 2),
                          "test_flagged": round(100 * b[metric].mean(), 2), "test_others": round(100 * rest_b[metric].mean(), 2),
                          "test_orders": len(b), "persistence": round(gap_b / gap_a, 2)}
    if col == "flag_dispatch":                      # late orders caused by dispatch, for the pilot
        R["holdout"][name]["test_dispatch_late_rate_flagged"] = round(100 * (b.late_cause == "dispatch").mean(), 2)
        R["holdout"][name]["test_dispatch_late_rate_others"] = round(100 * (rest_b.late_cause == "dispatch").mean(), 2)
print("\n== Holdout\n", json.dumps(R["holdout"], indent=1))
persistence = R["holdout"]["dispatch miss flag"]["persistence"]

# ---- 5. pilot simulation: coach the sellers flagged for missing dispatch deadlines ----
# Late orders avoided per year, with three sources of uncertainty: sampling noise (binomial draw per seller),
# how much of the gap persists (from the holdout), and how well coaching works (unknown, so drawn from a wide
# range instead of assumed).
pilot = s[s.flag_dispatch].sort_values("late_dispatch", ascending=False)
months = o.purchase_month.nunique()
sims = []
for _ in range(5000):
    effect = rng.uniform(0.15, 0.50)                 # share of dispatch caused late orders removed by coaching
    persist = np.clip(rng.normal(persistence, 0.15), 0.1, 1.0)
    avoided = rng.binomial(pilot.orders.to_numpy(), (pilot.late_dispatch / pilot.orders).to_numpy()).sum()
    sims.append(avoided * persist * effect * 12 / months)
sims = np.array(sims)
R["pilot"] = {"sellers": len(pilot), "orders": int(pilot.orders.sum()),
              "late_orders": int(pilot.late_orders.sum()), "late_dispatch": int(pilot.late_dispatch.sum()),
              "persistence": persistence,
              "avoided_per_year_p10": round(float(np.percentile(sims, 10))),
              "avoided_per_year_p50": round(float(np.percentile(sims, 50))),
              "avoided_per_year_p90": round(float(np.percentile(sims, 90))),
              "avg_value_of_late_order": round(float(o[o.is_late == 1].order_value.mean()), 2),
              "months_of_data": int(months), "effect_range": [0.15, 0.50]}
print("\n== Pilot simulation\n", json.dumps(R["pilot"], indent=1))
s = s.reset_index()

# ---- 5b. lanes: do bad lanes stay bad, and what would a longer promise buy? ----
ln_tr = train.groupby("lane").is_late.agg(["sum", "size"])
ln_tr["lo"], _ = wilson(ln_tr["sum"], ln_tr["size"])
bad = ln_tr.index[(ln_tr["size"] >= 200) & (ln_tr.lo > train.is_late.mean())]
a, b = train[train.lane.isin(bad)], test[test.lane.isin(bad)]
ra, rb = train[~train.lane.isin(bad)], test[~test.lane.isin(bad)]
R["lane_holdout"] = {"lanes_flagged": list(bad), "train_flagged": round(100 * a.is_late.mean(), 2),
                     "train_others": round(100 * ra.is_late.mean(), 2),
                     "test_flagged": round(100 * b.is_late.mean(), 2), "test_others": round(100 * rb.is_late.mean(), 2),
                     "persistence": round((b.is_late.mean() - rb.is_late.mean()) / (a.is_late.mean() - ra.is_late.mean()), 2)}
print("\n== Lane holdout\n", json.dumps(R["lane_holdout"], indent=1))

# Promise buffer: add k days to the delivery estimate on the persistently bad lanes. A late order whose excess
# is k days or less would have been on time. Evaluated on the holdout months only.
buf = test[test.lane.isin(bad)]
R["promise_buffer"] = {"lanes": len(bad), "test_orders": len(buf), "test_late": int(buf.is_late.sum()),
                       "share_of_all_test_late": round(100 * buf.is_late.sum() / test.is_late.sum(), 1),
                       "avg_promised_days": round(float(buf.promised_days.mean()), 1),
                       "avoided_by_days": {str(k): int(((buf.is_late == 1) & (buf.excess_days <= k)).sum()) for k in range(1, 8)},
                       "months": int(test.purchase_month.nunique())}
print("\n== Promise buffer\n", json.dumps(R["promise_buffer"], indent=1))

# ---- 6. query plans: seller drill through before and after an index ----
q = ("SELECT purchase_month, COUNT(*), SUM(is_late) FROM mart_orders "
     "WHERE seller_id = ? GROUP BY purchase_month")
sid = s.sort_values("orders", ascending=False).seller_id.iloc[0]
con.execute("DROP INDEX IF EXISTS ix_orders_seller_month")
def timed():
    t = time.perf_counter()
    for _ in range(200):
        con.execute(q, (sid,)).fetchall()
    return (time.perf_counter() - t) / 200 * 1000
plan = lambda: "\n".join(r[3] for r in con.execute("EXPLAIN QUERY PLAN " + q, (sid,)))
before_plan, before_ms = plan(), timed()
con.execute("CREATE INDEX ix_orders_seller_month ON mart_orders (seller_id, purchase_month, is_late)")
after_plan, after_ms = plan(), timed()
R["query_plan"] = {"before_ms": round(before_ms, 3), "after_ms": round(after_ms, 3)}
(ROOT / "docs" / "query_plans.md").write_text(f"""# Query plans

The seller drill through runs this query once per click:

```sql
{q}
```

| | Plan | Mean time over 200 runs |
|---|---|---|
| Before | `{before_plan}` | {before_ms:.2f} ms |
| After `CREATE INDEX ix_orders_seller_month ON mart_orders (seller_id, purchase_month, is_late)` | `{after_plan}` | {after_ms:.3f} ms |

The first plan scans all {len(o):,} rows. The second reads only the index, and because the index covers every
column the query needs, SQLite never touches the table. Speed up: about {before_ms / after_ms:.0f}x.

The marts themselves avoid the costly pattern altogether: child tables are aggregated to one row per order once,
at build time, so no report query joins orders to items, payments or reviews.
""")
print("\n== Query plan\n", before_plan, f"{before_ms:.2f} ms ->", after_plan, f"{after_ms:.3f} ms")
con.commit()

s.to_csv(ROOT / "data" / "seller_scorecard.csv", index=False)
R["scope"] = {"orders": len(o), "sellers": len(s), "from": o.purchase_month.min(), "to": o.purchase_month.max(),
              "multi_seller_orders": int((o.sellers > 1).sum())}
(ROOT / "data" / "results.json").write_text(json.dumps(R, indent=1, default=float))
