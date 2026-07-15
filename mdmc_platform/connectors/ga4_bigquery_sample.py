from __future__ import annotations

from mdmc_platform.connectors.base import BaseConnector, ExtractResult, ExtractedTable


class Ga4BigQuerySampleConnector(BaseConnector):
    registry_key = "ga4_bigquery_sample"
    source_category = "web_analytics"

    def extract(self, warehouse, completed_extracts: list[ExtractResult]) -> ExtractResult:
        del completed_extracts
        table_name = self.source.params.get("table_name", self.build_table_name())
        table_fqn = self.config.raw_table_fqn(table_name)
        sql = f"""
CREATE OR REPLACE TABLE `{table_fqn}` AS
WITH events AS (
  SELECT
    PARSE_DATE('%Y%m%d', event_date) AS source_date,
    COALESCE(NULLIF(traffic_source.source, ''), '(direct)') AS source,
    COALESCE(NULLIF(traffic_source.medium, ''), '(none)') AS medium,
    COALESCE(NULLIF(traffic_source.name, ''), '(not set)') AS campaign,
    user_pseudo_id,
    event_name,
    ecommerce.purchase_revenue_in_usd AS purchase_revenue,
    (
      SELECT value.int_value
      FROM UNNEST(event_params)
      WHERE key = 'ga_session_id'
    ) AS ga_session_id
  FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`
  WHERE _TABLE_SUFFIX BETWEEN '20201101' AND '20210131'
),
aggregated AS (
  SELECT
    source_date,
    source_date AS date,
    source,
    medium,
    campaign,
    COUNT(DISTINCT CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING))) AS sessions,
    COUNT(DISTINCT user_pseudo_id) AS users,
    COUNT(DISTINCT IF(event_name = 'first_visit', user_pseudo_id, NULL)) AS new_users,
    COUNT(DISTINCT IF(event_name = 'user_engagement', CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING)), NULL)) AS engaged_sessions,
    COUNTIF(event_name = 'purchase') AS purchases,
    ROUND(SUM(IFNULL(purchase_revenue, 0)), 2) AS purchase_revenue
  FROM events
  GROUP BY 1, 2, 3, 4, 5
)
SELECT *
FROM aggregated
"""
        warehouse.run_sql(sql)
        return ExtractResult(
            source_name=self.source.name,
            source_category=self.source_category,
            tables=(
                ExtractedTable(
                    source_name=self.source.name,
                    source_category=self.source_category,
                    table_name=table_name,
                    table_fqn=table_fqn,
                ),
            ),
        )
