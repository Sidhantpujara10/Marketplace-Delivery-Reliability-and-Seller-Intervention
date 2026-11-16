-- Marts. Every join below is made grain safe by pre-aggregating the child table to one row per
-- order BEFORE joining. Joining orders straight to items, payments and reviews would fan out rows
-- and double count value (items: 112,650 rows for 98,666 orders; payments: 103,886; reviews: 99,224).

-- ---------- one row per order from each child table ----------
DROP TABLE IF EXISTS int_order_items;
CREATE TABLE int_order_items AS
WITH seller_value AS (          -- value each seller contributes to each order
    SELECT order_id, seller_id, SUM(price) AS seller_price,
           ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY SUM(price) DESC, seller_id) AS rn
    FROM stg_order_items GROUP BY order_id, seller_id
),
category_value AS (             -- value each category contributes to each order
    SELECT i.order_id, COALESCE(t.product_category_name_english, p.product_category_name, 'unknown') AS category,
           ROW_NUMBER() OVER (PARTITION BY i.order_id ORDER BY SUM(i.price) DESC) AS rn
    FROM stg_order_items i
    LEFT JOIN stg_products p       ON p.product_id = i.product_id
    LEFT JOIN stg_category_names t ON t.product_category_name = p.product_category_name
    GROUP BY i.order_id, 2
),
totals AS (
    SELECT order_id, COUNT(*) AS items, COUNT(DISTINCT seller_id) AS sellers,
           SUM(price) AS item_value, SUM(freight_value) AS freight_value,
           MAX(shipping_limit_date) AS shipping_limit
    FROM stg_order_items GROUP BY order_id
)
SELECT t.*, s.seller_id AS primary_seller_id, c.category AS primary_category
FROM totals t
JOIN seller_value s   ON s.order_id = t.order_id AND s.rn = 1
JOIN category_value c ON c.order_id = t.order_id AND c.rn = 1;

DROP TABLE IF EXISTS int_order_payments;
CREATE TABLE int_order_payments AS
SELECT order_id, SUM(payment_value) AS payment_value FROM stg_payments GROUP BY order_id;

DROP TABLE IF EXISTS int_order_reviews;
CREATE TABLE int_order_reviews AS
SELECT order_id, AVG(review_score) AS review_score FROM stg_reviews GROUP BY order_id;

-- ---------- order mart: grain = one delivered order ----------
DROP TABLE IF EXISTS mart_orders;
CREATE TABLE mart_orders AS
SELECT o.order_id,
       DATE(o.order_purchase_timestamp)                 AS purchase_date,
       SUBSTR(o.order_purchase_timestamp, 1, 7)         AS purchase_month,
       i.primary_seller_id                              AS seller_id,
       s.seller_state, s.seller_city,
       c.customer_state,
       s.seller_state || ' > ' || c.customer_state      AS lane,
       i.primary_category                               AS category,
       i.items, i.sellers, i.item_value, i.freight_value,
       COALESCE(p.payment_value, i.item_value + i.freight_value) AS order_value,
       r.review_score,
       -- stage durations in days
       ROUND(JULIANDAY(o.order_delivered_carrier_date) - JULIANDAY(o.order_approved_at), 2)             AS dispatch_days,
       ROUND(JULIANDAY(o.order_delivered_customer_date) - JULIANDAY(o.order_delivered_carrier_date), 2) AS transit_days,
       ROUND(JULIANDAY(o.order_delivered_customer_date) - JULIANDAY(o.order_purchase_timestamp), 2)     AS total_days,
       ROUND(JULIANDAY(DATE(o.order_estimated_delivery_date)) - JULIANDAY(DATE(o.order_purchase_timestamp))) AS promised_days,
       -- outcome flags
       (DATE(o.order_delivered_customer_date) > DATE(o.order_estimated_delivery_date))                  AS is_late,
       MAX(0, JULIANDAY(DATE(o.order_delivered_customer_date)) - JULIANDAY(DATE(o.order_estimated_delivery_date))) AS excess_days,
       (o.order_delivered_carrier_date > i.shipping_limit)                                              AS dispatch_late,
       -- cause of a late order: the seller missed the handover deadline, or the carrier lost the time
       CASE WHEN DATE(o.order_delivered_customer_date) <= DATE(o.order_estimated_delivery_date) THEN 'on_time'
            WHEN o.order_delivered_carrier_date > i.shipping_limit THEN 'dispatch'
            ELSE 'transit' END                                                                          AS late_cause
FROM stg_orders o
JOIN int_order_items i        ON i.order_id = o.order_id
JOIN stg_sellers s            ON s.seller_id = i.primary_seller_id
JOIN stg_customers c          ON c.customer_id = o.customer_id
LEFT JOIN int_order_payments p ON p.order_id = o.order_id
LEFT JOIN int_order_reviews r  ON r.order_id = o.order_id
WHERE o.order_status = 'delivered'
  AND o.order_purchase_timestamp >= '2017-01-01' AND o.order_purchase_timestamp < '2018-09-01'
  AND o.order_approved_at IS NOT NULL
  AND o.order_delivered_carrier_date IS NOT NULL
  AND o.order_delivered_customer_date IS NOT NULL
  AND o.order_delivered_carrier_date >= o.order_approved_at            -- drop impossible timestamps
  AND o.order_delivered_customer_date >= o.order_delivered_carrier_date;

CREATE UNIQUE INDEX ux_mart_orders ON mart_orders (order_id);

-- ---------- daily mart with a 28 day rolling late rate ----------
DROP TABLE IF EXISTS mart_daily;
CREATE TABLE mart_daily AS
WITH d AS (
    SELECT purchase_date, COUNT(*) AS orders, SUM(is_late) AS late FROM mart_orders GROUP BY purchase_date
)
SELECT purchase_date, orders, late,
       SUM(orders) OVER w AS orders_28d,
       SUM(late)   OVER w AS late_28d,
       ROUND(100.0 * SUM(late) OVER w / SUM(orders) OVER w, 2) AS late_rate_28d
FROM d
WINDOW w AS (ORDER BY JULIANDAY(purchase_date) RANGE BETWEEN 27 PRECEDING AND CURRENT ROW);

-- ---------- seller mart: grain = one seller ----------
DROP TABLE IF EXISTS mart_sellers;
CREATE TABLE mart_sellers AS
WITH ranked AS (                 -- percentile of dispatch time inside each seller
    SELECT seller_id, dispatch_days,
           PERCENT_RANK() OVER (PARTITION BY seller_id ORDER BY dispatch_days) AS pr
    FROM mart_orders
)
SELECT m.seller_id, m.seller_state, m.seller_city,
       MIN(m.purchase_month)                                   AS cohort_month,
       COUNT(*)                                                AS orders,
       SUM(m.is_late)                                          AS late_orders,
       ROUND(100.0 * AVG(m.is_late), 2)                        AS late_rate,
       SUM(m.late_cause = 'dispatch')                          AS late_dispatch,
       SUM(m.late_cause = 'transit')                           AS late_transit,
       ROUND(100.0 * AVG(m.dispatch_late), 2)                  AS dispatch_miss_rate,
       ROUND(SUM(m.excess_days), 0)                            AS excess_days,
       ROUND(SUM(m.order_value), 2)                            AS order_value,
       ROUND(SUM(m.order_value * m.is_late), 2)                AS late_value,
       ROUND(AVG(m.review_score), 2)                           AS review_score,
       (SELECT ROUND(MIN(r.dispatch_days), 2) FROM ranked r WHERE r.seller_id = m.seller_id AND r.pr >= 0.5) AS dispatch_p50,
       (SELECT ROUND(MIN(r.dispatch_days), 2) FROM ranked r WHERE r.seller_id = m.seller_id AND r.pr >= 0.9) AS dispatch_p90
FROM mart_orders m GROUP BY m.seller_id;

CREATE UNIQUE INDEX ux_mart_sellers ON mart_sellers (seller_id);
