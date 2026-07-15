-- Builds the core paid-media mart so marketing spend and GA4 outcomes can be reviewed together.
-- This is the primary cross-source performance table for dashboards and downstream QA.
CREATE OR REPLACE TABLE `${daily_performance_table}` AS
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
    SUM(sessions) AS ga4_sessions,
    SUM(purchases) AS ga4_purchases,
    SUM(purchase_revenue) AS ga4_revenue
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
    SUM(spend) AS spend,
    SUM(clicks) AS clicks,
    SUM(impressions) AS impressions,
    SUM(platform_reported_conversions) AS platform_conversions
  FROM (
${ad_platform_union_sql}
  )
  GROUP BY 1, 2, 3, 4
)
SELECT
  a.date,
  a.platform,
  a.campaign,
  ROUND(a.spend, 2) AS spend,
  a.clicks,
  a.impressions,
  COALESCE(w.ga4_sessions, 0) AS ga4_sessions,
  COALESCE(w.ga4_purchases, 0) AS ga4_purchases,
  ROUND(COALESCE(w.ga4_revenue, 0), 2) AS ga4_revenue,
  a.platform_conversions,
  ROUND(SAFE_DIVIDE(a.spend, NULLIF(w.ga4_purchases, 0)), 2) AS cpa,
  ROUND(SAFE_DIVIDE(w.ga4_revenue, NULLIF(a.spend, 0)), 4) AS roas
FROM ad_platform AS a
LEFT JOIN web_analytics AS w
  ON a.date = w.date
 AND LOWER(a.campaign) = LOWER(w.campaign)
