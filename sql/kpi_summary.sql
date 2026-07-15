-- Builds a rolling-window scorecard so the dashboard has one compact summary of the recent operating picture.
-- Booking metrics become null instead of failing when a client has no booking-system connector configured.
CREATE OR REPLACE TABLE `${kpi_summary_table}` AS
WITH performance_window AS (
  SELECT *
  FROM `${daily_performance_table}`
  WHERE date >= DATE_SUB((SELECT MAX(date) FROM `${daily_performance_table}`), INTERVAL ${rolling_window_days_minus_one} DAY)
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
  MIN(date) AS window_start,
  MAX(date) AS window_end,
  ROUND(SUM(spend), 2) AS spend,
  SUM(clicks) AS clicks,
  SUM(impressions) AS impressions,
  SUM(ga4_sessions) AS ga4_sessions,
  SUM(ga4_purchases) AS ga4_purchases,
  ROUND(SUM(ga4_revenue), 2) AS ga4_revenue,
  SUM(platform_conversions) AS platform_conversions,
  ROUND(SAFE_DIVIDE(SUM(spend), NULLIF(booking_window.appointments_booked, 0)), 2) AS cost_per_booking,
  ROUND(SAFE_DIVIDE(booking_window.no_shows, NULLIF(booking_window.appointments_booked, 0)), 4) AS no_show_rate,
  reconciliation_summary.reconciliation_flag_count AS reconciliation_flag_count
FROM performance_window
CROSS JOIN booking_window
CROSS JOIN reconciliation_summary
