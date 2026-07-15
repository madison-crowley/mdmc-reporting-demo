-- Builds the local-service funnel mart so spend, traffic, and bookings can be assessed in one line of sight.
-- This turns the demo booking export into a buyer-friendly daily funnel.
CREATE OR REPLACE TABLE `${booking_funnel_table}` AS
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
bookings AS (
  SELECT
    DATE_ADD(source_date, INTERVAL (SELECT shift_days FROM shift) DAY) AS date,
    source_date,
    SUM(appointments_booked) AS appointments_booked,
    SUM(appointments_completed) AS appointments_completed,
    SUM(no_shows) AS no_shows,
    ROUND(SUM(booking_revenue), 2) AS booking_revenue
  FROM (
${booking_system_union_sql}
  )
  GROUP BY 1, 2
),
performance AS (
  SELECT
    date,
    ROUND(SUM(spend), 2) AS spend,
    SUM(ga4_sessions) AS ga4_sessions
  FROM `${daily_performance_table}`
  GROUP BY 1
)
SELECT
  COALESCE(performance.date, bookings.date) AS date,
  ROUND(COALESCE(performance.spend, 0), 2) AS spend,
  COALESCE(performance.ga4_sessions, 0) AS ga4_sessions,
  COALESCE(bookings.appointments_booked, 0) AS appointments_booked,
  COALESCE(bookings.appointments_completed, 0) AS appointments_completed,
  ROUND(COALESCE(bookings.booking_revenue, 0), 2) AS booking_revenue,
  ROUND(SAFE_DIVIDE(performance.spend, NULLIF(bookings.appointments_booked, 0)), 2) AS cost_per_booking,
  ROUND(SAFE_DIVIDE(bookings.booking_revenue, NULLIF(performance.spend, 0)), 4) AS revenue_per_spend_dollar
FROM performance
FULL OUTER JOIN bookings
  ON performance.date = bookings.date
