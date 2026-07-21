from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys

from google.cloud import bigquery


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from mdmc_platform.auth import create_bigquery_client
from mdmc_platform.config import PipelineConfig
from mdmc_platform.connectors.ga4_bigquery_sample import build_ga4_extraction_query
from mdmc_platform.transform import build_booking_window_sql, render_sql_template


MART_FIXTURE_SQL = {
    "daily_performance": """
SELECT
  DATE '2021-01-01' AS date,
  'Google Ads' AS platform,
  'Search | Brand Core' AS campaign,
  CAST(400.0 AS FLOAT64) AS spend,
  CAST(250 AS INT64) AS clicks,
  CAST(10000 AS INT64) AS impressions,
  CAST(120 AS INT64) AS ga4_sessions,
  CAST(10 AS INT64) AS ga4_purchases,
  CAST(250.0 AS FLOAT64) AS ga4_revenue,
  CAST(11 AS INT64) AS platform_conversions,
  CAST(40.0 AS FLOAT64) AS cpa,
  CAST(0.625 AS FLOAT64) AS roas
""".strip(),
    "reconciliation": """
SELECT
  DATE '2021-01-01' AS date,
  'Google Ads' AS platform,
  CAST(10 AS INT64) AS ga4_purchases,
  CAST(11 AS INT64) AS platform_conversions,
  CAST(1 AS INT64) AS absolute_discrepancy,
  CAST(10.0 AS FLOAT64) AS discrepancy_pct,
  'normal' AS baseline_status,
  FALSE AS is_flagged
""".strip(),
    "booking_funnel": """
SELECT
  DATE '2021-01-01' AS date,
  CAST(400.0 AS FLOAT64) AS spend,
  CAST(120 AS INT64) AS ga4_sessions,
  CAST(12 AS INT64) AS appointments_booked,
  CAST(10 AS INT64) AS appointments_completed,
  CAST(2 AS INT64) AS no_shows,
  CAST(1400.0 AS FLOAT64) AS booking_revenue,
  CAST(33.33 AS FLOAT64) AS cost_per_booking,
  CAST(3.5 AS FLOAT64) AS revenue_per_spend_dollar
""".strip(),
    "kpi_summary": """
SELECT
  CAST(28 AS INT64) AS rolling_window_days,
  DATE '2020-12-05' AS window_start,
  DATE '2021-01-01' AS window_end,
  CAST(400.0 AS FLOAT64) AS spend,
  CAST(250 AS INT64) AS clicks,
  CAST(10000 AS INT64) AS impressions,
  CAST(120 AS INT64) AS ga4_sessions,
  CAST(10 AS INT64) AS ga4_purchases,
  CAST(250.0 AS FLOAT64) AS ga4_revenue,
  CAST(11 AS INT64) AS platform_conversions,
  CAST(33.33 AS FLOAT64) AS cost_per_booking,
  CAST(0.1667 AS FLOAT64) AS no_show_rate,
  CAST(1 AS INT64) AS reconciliation_flag_count
""".strip(),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="BigQuery dry-run lint for rendered SQL.")
    parser.add_argument("--config", default="configs/demo.yaml", help="Path to the deployment config.")
    return parser.parse_args()


def strip_create_prefix(sql: str) -> str:
    marker = " AS\n"
    _, _, query_body = sql.partition(marker)
    if not query_body:
        raise ValueError("Expected CREATE OR REPLACE TABLE ... AS SQL.")
    return query_body


def build_lint_context(config: PipelineConfig) -> dict[str, str]:
    return {
        "daily_performance_table": "lint_daily_performance",
        "reconciliation_table": "lint_reconciliation",
        "booking_funnel_table": "lint_booking_funnel",
        "kpi_summary_table": "lint_kpi_summary",
        "web_analytics_union_sql": """
SELECT
  DATE '2021-01-01' AS source_date,
  DATE '2021-01-01' AS date,
  'google' AS source,
  'cpc' AS medium,
  'Holiday Search' AS campaign,
  120 AS sessions,
  90 AS users,
  25 AS new_users,
  70 AS engaged_sessions,
  10 AS purchases,
  250.0 AS purchase_revenue
""".strip(),
        "ad_platform_union_sql": """
SELECT
  DATE '2021-01-01' AS source_date,
  DATE '2021-01-01' AS date,
  'Google Ads' AS platform,
  'Search | Brand Core' AS campaign_name,
  'Holiday Search' AS matched_ga4_campaign,
  10000 AS impressions,
  250 AS clicks,
  400.0 AS spend,
  11 AS platform_reported_conversions
""".strip(),
        "booking_system_union_sql": """
SELECT
  DATE '2021-01-01' AS source_date,
  DATE '2021-01-01' AS date,
  DATE '2021-01-01' AS booking_date,
  'facial' AS service_category,
  12 AS appointments_booked,
  10 AS appointments_completed,
  2 AS no_shows,
  1400.0 AS booking_revenue,
  'google / cpc' AS acquisition_channel
""".strip(),
        "max_source_date_union_sql": "SELECT DATE '2021-01-01' AS source_date",
        "source_max_date_union_sql": """
SELECT 'ad_platform' AS source_category, DATE '2021-01-01' AS max_date
UNION ALL
SELECT 'booking_system', DATE '2021-01-01'
UNION ALL
SELECT 'web_analytics', DATE '2021-01-01'
""".strip(),
        "date_shift_enabled": "TRUE" if config.transforms.date_shift else "FALSE",
        "reconciliation_threshold_pct": str(config.transforms.reconciliation_threshold_pct),
        "rolling_window_days": str(config.transforms.rolling_window_days),
        "rolling_window_days_minus_one": str(config.transforms.rolling_window_days - 1),
        "booking_window_sql": build_booking_window_sql(
            "lint_daily_performance",
            "lint_booking_funnel",
            config.transforms.rolling_window_days,
        ),
    }


def _inline_dependencies(query: str) -> str:
    replacements = {
        "lint_daily_performance": MART_FIXTURE_SQL["daily_performance"],
        "lint_reconciliation": MART_FIXTURE_SQL["reconciliation"],
        "lint_booking_funnel": MART_FIXTURE_SQL["booking_funnel"],
    }
    fixture_ctes = []
    for table_name, fixture_sql in replacements.items():
        quoted_table = f"`{table_name}`"
        if quoted_table not in query:
            continue
        query = query.replace(quoted_table, table_name)
        fixture_ctes.append(f"{table_name} AS (\n{fixture_sql}\n)")
    if not fixture_ctes:
        return query
    stripped_query = query.lstrip()
    if not stripped_query.upper().startswith("WITH "):
        raise ValueError("Expected rendered mart query to begin with WITH.")
    return "WITH\n" + ",\n".join(fixture_ctes) + ",\n" + stripped_query[5:]


def build_lint_queries(config: PipelineConfig) -> dict[str, str]:
    context = build_lint_context(config)
    queries = {
        mart: _inline_dependencies(strip_create_prefix(render_sql_template(mart, context)))
        for mart in ("daily_performance", "reconciliation", "booking_funnel", "kpi_summary")
    }
    queries["ga4_extraction"] = build_ga4_extraction_query()
    return queries


def dry_run_queries(client, queries: dict[str, str]) -> None:
    job_config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
    for query_name, query in queries.items():
        try:
            client.query(query, job_config=job_config).result()
        except Exception as exc:
            raise RuntimeError(f"BigQuery dry-run failed for {query_name}: {exc}") from exc
        logging.getLogger(__name__).info("BigQuery dry-run lint succeeded for %s.", query_name)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = parse_args()
    config = PipelineConfig.load(args.config)
    client = create_bigquery_client(config.project_id)
    dry_run_queries(client, build_lint_queries(config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
