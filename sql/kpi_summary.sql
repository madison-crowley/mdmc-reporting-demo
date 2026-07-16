-- Builds a rolling-window scorecard so the dashboard has one compact summary of the recent operating picture.
-- Booking metrics become null instead of failing when a client has no booking-system connector configured.
CREATE OR REPLACE TABLE `${kpi_summary_table}` AS
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
performance_window AS (
  SELECT *
  FROM `${daily_performance_table}`
  WHERE date >= DATE_SUB((SELECT MAX(date) FROM `${daily_performance_table}`), INTERVAL ${rolling_window_days_minus_one} DAY)
),
performance_summary AS (
  SELECT
    MIN(date) AS window_start,
    MAX(date) AS window_end,
    ROUND(SUM(spend), 2) AS spend,
    SUM(clicks) AS clicks,
    SUM(impressions) AS impressions,
    SUM(platform_conversions) AS platform_conversions
  FROM performance_window
),
web_analytics_window AS (
  SELECT
    shifted_web_analytics.date,
    SUM(shifted_web_analytics.sessions) AS ga4_sessions,
    SUM(shifted_web_analytics.purchases) AS ga4_purchases,
    ROUND(SUM(shifted_web_analytics.purchase_revenue), 2) AS ga4_revenue
  FROM (
    SELECT
      DATE_ADD(source_date, INTERVAL (SELECT shift_days FROM shift) DAY) AS date,
      sessions,
      purchases,
      purchase_revenue
    FROM (
${web_analytics_union_sql}
    )
  ) AS shifted_web_analytics
  WHERE shifted_web_analytics.date >= DATE_SUB((SELECT MAX(date) FROM `${daily_performance_table}`), INTERVAL ${rolling_window_days_minus_one} DAY)
  GROUP BY 1
),
web_analytics_summary AS (
  SELECT
    SUM(ga4_sessions) AS ga4_sessions,
    SUM(ga4_purchases) AS ga4_purchases,
    ROUND(SUM(ga4_revenue), 2) AS ga4_revenue
  FROM web_analytics_window
),
reconciliation_window AS (
  SELECT *
  FROM `${reconciliation_table}`
  WHERE date >= DATE_SUB((SELECT MAX(date) FROM `${reconciliation_table}`), INTERVAL ${rolling_window_days_minus_one} DAY)
),
booking_window AS (
${booking_window_sql}
),
reconciliation_summary AS (
  SELECT COUNTIF(is_flagged) AS reconciliation_flag_count
  FROM reconciliation_window
)
SELECT
  ${rolling_window_days} AS rolling_window_days,
  performance_summary.window_start AS window_start,
  performance_summary.window_end AS window_end,
  performance_summary.spend AS spend,
  performance_summary.clicks AS clicks,
  performance_summary.impressions AS impressions,
  web_analytics_summary.ga4_sessions AS ga4_sessions,
  web_analytics_summary.ga4_purchases AS ga4_purchases,
  web_analytics_summary.ga4_revenue AS ga4_revenue,
  performance_summary.platform_conversions AS platform_conversions,
  ROUND(SAFE_DIVIDE(performance_summary.spend, NULLIF(booking_window.appointments_booked, 0)), 2) AS cost_per_booking,
  ROUND(SAFE_DIVIDE(booking_window.no_shows, NULLIF(booking_window.appointments_booked, 0)), 4) AS no_show_rate,
  reconciliation_summary.reconciliation_flag_count AS reconciliation_flag_count
FROM performance_summary
CROSS JOIN web_analytics_summary
CROSS JOIN booking_window
CROSS JOIN reconciliation_summary
