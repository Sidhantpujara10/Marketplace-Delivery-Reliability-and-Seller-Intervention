# Query plans

The seller drill through runs this query once per click:

```sql
SELECT purchase_month, COUNT(*), SUM(is_late) FROM mart_orders WHERE seller_id = ? GROUP BY purchase_month
```

| | Plan | Mean time over 200 runs |
|---|---|---|
| Before | `SCAN mart_orders
USE TEMP B-TREE FOR GROUP BY` | 8.64 ms |
| After `CREATE INDEX ix_orders_seller_month ON mart_orders (seller_id, purchase_month, is_late)` | `SEARCH mart_orders USING COVERING INDEX ix_orders_seller_month (seller_id=?)` | 0.158 ms |

The first plan scans all 94,819 rows. The second reads only the index, and because the index covers every
column the query needs, SQLite never touches the table. Speed up: about 55x.

The marts themselves avoid the costly pattern altogether: child tables are aggregated to one row per order once,
at build time, so no report query joins orders to items, payments or reviews.
