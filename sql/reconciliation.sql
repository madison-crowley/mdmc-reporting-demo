-- Builds the reconciliation mart so buyers can see where platform conversion counts diverge from GA4.
-- The flagged rows are expected talking points rather than automatic pipeline failures.
CREATE OR REPLACE TABLE `${reconciliation_table}` AS
WITH shift AS (
  SELECT
    CASE
      WHEN ${date_shift_enabled} THEN DATE_DIFF(DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY), MAX(source_date), DAY)
      ELSE 0
    END AS shift_days
  FROM (
${max_source_date_union_sql}
  )
),
web_analytics AS (
  SELECT
    DATE_ADD(source_date, INTERVAL (SELECT shift_days FROM shift) DAY) AS date,
    source_date,
    campaign,
    SUM(purchases) AS ga4_purchases
  FROM (
${web_analytics_union_sql}
  )
  GROUP BY 1, 2, 3
),
ad_platform AS (
  SELECT
    DATE_ADD(source_date, INTERVAL (SELECT shift_days FROM shift) DAY) AS date,
    source_date,
    platform,
    campaign_name AS campaign,
    SUM(platform_reported_conversions) AS platform_conversions
  FROM (
${ad_platform_union_sql}
  )
  GROUP BY 1, 2, 3, 4
),
scoped_performance AS (
  SELECT
    a.date,
    a.platform,
    COALESCE(w.ga4_purchases, 0) AS ga4_purchases,
    a.platform_conversions
  FROM ad_platform AS a
  LEFT JOIN web_analytics AS w
    ON a.date = w.date
   AND LOWER(a.campaign) = LOWER(w.campaign)
)
SELECT
  date,
  platform,
  SUM(ga4_purchases) AS ga4_purchases,
  SUM(platform_conversions) AS platform_conversions,
  ABS(SUM(platform_conversions) - SUM(ga4_purchases)) AS absolute_discrepancy,
  ROUND(
    SAFE_DIVIDE(SUM(platform_conversions) - SUM(ga4_purchases), NULLIF(SUM(ga4_purchases), 0)) * 100,
    2
  ) AS discrepancy_pct,
  ABS(
    ROUND(
      SAFE_DIVIDE(SUM(platform_conversions) - SUM(ga4_purchases), NULLIF(SUM(ga4_purchases), 0)) * 100,
      2
    )
  ) > ${reconciliation_threshold_pct} AS is_flagged
FROM scoped_performance
GROUP BY 1, 2
