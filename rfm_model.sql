-- =============================================================================
-- rfm_model.sql  |  PostgreSQL 12+
-- Builds customer-level Recency / Frequency / Monetary scores from the cleaned
-- transaction extract produced by data_cleaning.py.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. Staging table for the cleaned CSV
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS retail_transactions;

CREATE TABLE retail_transactions (
    invoice_no    VARCHAR(20)    NOT NULL,
    stock_code    VARCHAR(20)    NOT NULL,
    description   TEXT,
    quantity      INTEGER        NOT NULL,
    invoice_date  TIMESTAMP      NOT NULL,
    unit_price    NUMERIC(12, 2) NOT NULL,
    customer_id   INTEGER        NOT NULL,
    country       VARCHAR(60),
    total_price   NUMERIC(14, 2) NOT NULL
);

-- Load the cleaned file (server-side path). From psql use \copy instead:
--   \copy retail_transactions FROM 'data/clean/online_retail_clean.csv' CSV HEADER
COPY retail_transactions
FROM '/absolute/path/to/data/clean/online_retail_clean.csv'
WITH (FORMAT csv, HEADER true);

CREATE INDEX idx_retail_customer ON retail_transactions (customer_id);
CREATE INDEX idx_retail_date     ON retail_transactions (invoice_date);

ANALYZE retail_transactions;

-- -----------------------------------------------------------------------------
-- 2. RFM model
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS rfm_segments;

CREATE TABLE rfm_segments AS
WITH snapshot AS (
    -- Anchor date: one day after the last transaction in the dataset, so the
    -- most recent buyer gets a recency of 1 rather than 0.
    SELECT (MAX(invoice_date)::date + INTERVAL '1 day')::date AS snapshot_date
    FROM   retail_transactions
),

customer_metrics AS (
    SELECT
        t.customer_id,
        MAX(t.invoice_date)::date                             AS last_purchase_date,
        (s.snapshot_date - MAX(t.invoice_date)::date)::int     AS recency,
        COUNT(DISTINCT t.invoice_no)::int                      AS frequency,
        ROUND(SUM(t.total_price), 2)                           AS monetary,
        ROUND(SUM(t.total_price) / COUNT(DISTINCT t.invoice_no), 2) AS avg_order_value,
        MIN(t.invoice_date)::date                              AS first_purchase_date,
        MAX(t.country)                                         AS country
    FROM retail_transactions t
    CROSS JOIN snapshot s
    GROUP BY t.customer_id, s.snapshot_date
),

rfm_scores AS (
    SELECT
        cm.*,
        -- Recency DESC => the largest (worst) recency lands in quintile 1 and
        -- the smallest (most recent) lands in quintile 5.
        NTILE(5) OVER (ORDER BY cm.recency   DESC)              AS r_score,
        NTILE(5) OVER (ORDER BY cm.frequency ASC, cm.recency DESC) AS f_score,
        NTILE(5) OVER (ORDER BY cm.monetary  ASC)               AS m_score
    FROM customer_metrics cm
)

SELECT
    customer_id,
    country,
    first_purchase_date,
    last_purchase_date,
    recency,
    frequency,
    monetary,
    avg_order_value,
    r_score,
    f_score,
    m_score,
    (r_score + f_score + m_score)                     AS rfm_sum,
    CONCAT(r_score::text, f_score::text, m_score::text) AS rfm_score,
    -- Business segment. Mirrors the SWITCH(TRUE()) in power_bi_dax.txt so the
    -- label is identical in every downstream tool, not just in Power BI.
    CASE
        WHEN CONCAT(r_score::text, f_score::text, m_score::text)
             IN ('555','554','544','545','454','455','445')
            THEN 'Champions'
        WHEN CONCAT(r_score::text, f_score::text, m_score::text)
             IN ('543','444','435','355','354','345','344','335')
            THEN 'Loyal Customers'
        WHEN CONCAT(r_score::text, f_score::text, m_score::text)
             IN ('553','551','552','541','542','533','532','531','452','451',
                 '442','441','431','453','433','432','423','353','352','351',
                 '342','341','333','323')
            THEN 'Potential Loyalist'
        WHEN CONCAT(r_score::text, f_score::text, m_score::text)
             IN ('512','511','422','421','412','411','311')
            THEN 'New Customers'
        WHEN CONCAT(r_score::text, f_score::text, m_score::text)
             IN ('525','524','523','522','521','515','514','513','425','424',
                 '413','414','415','315','314','313')
            THEN 'Promising'
        WHEN CONCAT(r_score::text, f_score::text, m_score::text)
             IN ('535','534','443','434','343','334','325','324')
            THEN 'Needs Attention'
        WHEN CONCAT(r_score::text, f_score::text, m_score::text)
             IN ('331','321','312','221','213','231','241','251')
            THEN 'About To Sleep'
        WHEN CONCAT(r_score::text, f_score::text, m_score::text)
             IN ('255','254','245','244','253','252','243','242','235','234',
                 '225','224','153','152','145','143','142','135','134','133',
                 '125','124')
            THEN 'At Risk'
        WHEN CONCAT(r_score::text, f_score::text, m_score::text)
             IN ('155','154','144','214','215','115','114','113')
            THEN 'Cannot Lose Them'
        WHEN CONCAT(r_score::text, f_score::text, m_score::text)
             IN ('111','112','121','131','141','151')
            THEN 'Lost'
        -- Fall-through for any code not listed above.
        WHEN r_score >= 4 AND f_score >= 4 THEN 'Champions'
        WHEN r_score >= 4 AND f_score >= 2 THEN 'Potential Loyalist'
        WHEN r_score >= 4                  THEN 'New Customers'
        WHEN r_score  = 3 AND f_score >= 3 THEN 'Loyal Customers'
        WHEN r_score  = 3                  THEN 'Needs Attention'
        WHEN r_score  = 2 AND f_score >= 3 THEN 'At Risk'
        WHEN r_score <= 2 AND m_score >= 4 THEN 'Cannot Lose Them'
        WHEN r_score  = 2                  THEN 'About To Sleep'
        WHEN r_score  = 1 AND f_score >= 3 THEN 'At Risk'
        ELSE 'Hibernating'
    END AS customer_segment
FROM rfm_scores;

ALTER TABLE rfm_segments ADD PRIMARY KEY (customer_id);
CREATE INDEX idx_rfm_score ON rfm_segments (rfm_score);
CREATE INDEX idx_rfm_segment ON rfm_segments (customer_segment);

ANALYZE rfm_segments;

-- -----------------------------------------------------------------------------
-- 3. Validation
-- -----------------------------------------------------------------------------
-- Quintile sanity check: each score bucket should hold ~20% of customers.
SELECT r_score,
       COUNT(*)                                            AS customers,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1)  AS pct,
       MIN(recency)                                        AS min_recency,
       MAX(recency)                                        AS max_recency
FROM rfm_segments
GROUP BY r_score
ORDER BY r_score DESC;

-- Segment distribution: customer share vs revenue share.
SELECT customer_segment,
       COUNT(*)                                                      AS customers,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1)            AS pct_customers,
       ROUND(SUM(monetary), 2)                                       AS revenue,
       ROUND(100.0 * SUM(monetary) / SUM(SUM(monetary)) OVER (), 1)  AS pct_revenue
FROM rfm_segments
GROUP BY customer_segment
ORDER BY revenue DESC;

-- Top 20 customers by RFM score.
SELECT customer_id, recency, frequency, monetary, rfm_score
FROM rfm_segments
ORDER BY rfm_sum DESC, monetary DESC
LIMIT 20;

-- -----------------------------------------------------------------------------
-- 4. Power BI consumption views
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW vw_rfm_segments AS
SELECT * FROM rfm_segments;

-- Fact view: transactions enriched with the customer's RFM score.
CREATE OR REPLACE VIEW vw_sales_fact AS
SELECT
    t.invoice_no,
    t.invoice_date,
    t.customer_id,
    t.stock_code,
    t.description,
    t.quantity,
    t.unit_price,
    t.total_price,
    t.country,
    r.rfm_score,
    r.customer_segment
FROM retail_transactions t
JOIN rfm_segments r ON r.customer_id = t.customer_id;
