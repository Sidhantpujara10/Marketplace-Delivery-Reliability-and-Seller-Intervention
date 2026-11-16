-- Analysis queries. Run by pipeline/03_analyse.py, which prints each result.

-- 1. Scorecard
SELECT COUNT(*) AS orders, SUM(is_late) AS late_orders,
       ROUND(100.0 * AVG(is_late), 2) AS late_rate,
       ROUND(100.0 * AVG(dispatch_late), 2) AS dispatch_miss_rate,
       ROUND(SUM(excess_days)) AS excess_days,
       ROUND(SUM(order_value * is_late)) AS late_value,
       ROUND(100.0 * SUM(order_value * is_late) / SUM(order_value), 2) AS late_value_pct
FROM mart_orders;

-- 2. Where the time is lost: cause of late orders
SELECT late_cause, COUNT(*) AS orders,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct_of_late,
       ROUND(AVG(excess_days), 1) AS avg_excess_days, ROUND(AVG(review_score), 2) AS avg_review
FROM mart_orders WHERE is_late GROUP BY late_cause;

-- 3. Percentile delays (window functions; SQLite has no PERCENTILE_CONT)
WITH r AS (
    SELECT dispatch_days, transit_days,
           PERCENT_RANK() OVER (ORDER BY dispatch_days) AS pd,
           PERCENT_RANK() OVER (ORDER BY transit_days)  AS pt
    FROM mart_orders
)
SELECT 'dispatch_days' AS metric,
       (SELECT MIN(dispatch_days) FROM r WHERE pd >= 0.50) AS p50,
       (SELECT MIN(dispatch_days) FROM r WHERE pd >= 0.90) AS p90,
       (SELECT MIN(dispatch_days) FROM r WHERE pd >= 0.95) AS p95
UNION ALL
SELECT 'transit_days',
       (SELECT MIN(transit_days) FROM r WHERE pt >= 0.50),
       (SELECT MIN(transit_days) FROM r WHERE pt >= 0.90),
       (SELECT MIN(transit_days) FROM r WHERE pt >= 0.95);

-- 4. Excess days among late orders
WITH r AS (SELECT excess_days, PERCENT_RANK() OVER (ORDER BY excess_days) AS p FROM mart_orders WHERE is_late)
SELECT (SELECT MIN(excess_days) FROM r WHERE p >= 0.50) AS p50,
       (SELECT MIN(excess_days) FROM r WHERE p >= 0.90) AS p90,
       (SELECT MIN(excess_days) FROM r WHERE p >= 0.95) AS p95;

-- 5. Seller concentration: cumulative share of late orders (Pareto)
WITH s AS (
    SELECT seller_id, late_orders, orders,
           ROW_NUMBER() OVER (ORDER BY late_orders DESC, seller_id) AS rnk,
           SUM(late_orders) OVER (ORDER BY late_orders DESC, seller_id) AS cum_late,
           SUM(orders)      OVER (ORDER BY late_orders DESC, seller_id) AS cum_orders
    FROM mart_sellers
)
SELECT rnk AS top_n_sellers,
       ROUND(100.0 * rnk / (SELECT COUNT(*) FROM mart_sellers), 1)             AS pct_of_sellers,
       ROUND(100.0 * cum_late / (SELECT SUM(late_orders) FROM mart_sellers), 1) AS pct_of_late_orders,
       ROUND(100.0 * cum_orders / (SELECT SUM(orders) FROM mart_sellers), 1)    AS pct_of_all_orders
FROM s WHERE rnk IN (10, 25, 50, 100, 146, 292);

-- 6. Lane concentration, minimum volume 200 orders
SELECT lane, COUNT(*) AS orders, SUM(is_late) AS late_orders,
       ROUND(100.0 * AVG(is_late), 1) AS late_rate,
       ROUND(100.0 * SUM(is_late) / (SELECT SUM(is_late) FROM mart_orders), 1) AS pct_of_all_late,
       ROUND(100.0 * AVG(late_cause = 'transit') / AVG(is_late), 0) AS pct_transit
FROM mart_orders GROUP BY lane HAVING COUNT(*) >= 200 ORDER BY late_orders DESC LIMIT 10;

-- 7. Seller cohorts: does reliability depend on when a seller joined?
SELECT SUBSTR(s.cohort_month, 1, 4) || ' H' || CASE WHEN SUBSTR(s.cohort_month, 6, 2) <= '06' THEN 1 ELSE 2 END AS cohort,
       COUNT(DISTINCT s.seller_id) AS sellers, COUNT(*) AS orders,
       ROUND(100.0 * AVG(m.is_late), 2) AS late_rate,
       ROUND(100.0 * AVG(m.dispatch_late), 2) AS dispatch_miss_rate
FROM mart_orders m JOIN mart_sellers s USING (seller_id)
WHERE m.purchase_month >= '2018-04'          -- same calendar window for every cohort
GROUP BY 1 ORDER BY 1;

-- 8. New sellers: first 30 days on the platform against later
WITH f AS (SELECT seller_id, MIN(purchase_date) AS first_date FROM mart_orders GROUP BY seller_id)
SELECT CASE WHEN JULIANDAY(m.purchase_date) - JULIANDAY(f.first_date) < 30 THEN 'first 30 days' ELSE 'after 30 days' END AS tenure,
       COUNT(*) AS orders, ROUND(100.0 * AVG(m.is_late), 2) AS late_rate,
       ROUND(100.0 * AVG(m.dispatch_late), 2) AS dispatch_miss_rate
FROM mart_orders m JOIN f USING (seller_id) GROUP BY 1;

-- 9. Cost signal: reviews for late against on time orders
SELECT CASE WHEN is_late THEN 'late' ELSE 'on time' END AS outcome, COUNT(*) AS reviewed_orders,
       ROUND(AVG(review_score), 2) AS avg_review,
       ROUND(100.0 * AVG(review_score <= 2), 1) AS pct_1_or_2_stars
FROM mart_orders WHERE review_score IS NOT NULL GROUP BY 1;
