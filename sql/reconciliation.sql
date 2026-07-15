-- Builds the reconciliation mart so buyers can see where platform conversion counts diverge from GA4.
-- The flagged rows are expected talking points rather than automatic pipeline failures.
CREATE OR REPLACE TABLE `${reconciliation_table}` AS
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
FROM `${daily_performance_table}`
GROUP BY 1, 2
