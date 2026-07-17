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
from mdmc_platform.transform import build_booking_window_sql, render_sql_template


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
UNION ALL
SELECT
  DATE '2021-01-01',
  DATE '2021-01-01',
  'facebook',
  'paid_social',
  'Injectables Promo',
  90,
  68,
  20,
  55,
  8,
  180.0
""".strip(),
        "ad_platform_union_sql": """
SELECT
  DATE '2021-01-01' AS source_date,
  DATE '2021-01-01' AS date,
  'Google Ads' AS platform,
  'Holiday Search' AS campaign_name,
  10000 AS impressions,
  250 AS clicks,
  400.0 AS spend,
  11 AS platform_reported_conversions
UNION ALL
SELECT
  DATE '2021-01-01',
  DATE '2021-01-01',
  'Meta Ads',
  'Injectables Promo',
  9000,
  220,
  360.0,
  7
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
        "max_source_date_union_sql": """
SELECT DATE '2021-01-01' AS source_date
UNION ALL
SELECT DATE '2021-01-02' AS source_date
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


def build_lint_script(config: PipelineConfig) -> str:
    context = build_lint_context(config)
    daily_performance_sql = strip_create_prefix(render_sql_template("daily_performance", context))
    reconciliation_sql = strip_create_prefix(render_sql_template("reconciliation", context))
    booking_funnel_sql = strip_create_prefix(render_sql_template("booking_funnel", context))
    kpi_summary_sql = strip_create_prefix(render_sql_template("kpi_summary", context))
    return f"""
CREATE TEMP TABLE lint_daily_performance AS
{daily_performance_sql};

CREATE TEMP TABLE lint_reconciliation AS
{reconciliation_sql};

CREATE TEMP TABLE lint_booking_funnel AS
{booking_funnel_sql};

CREATE TEMP TABLE lint_kpi_summary AS
{kpi_summary_sql};

SELECT 1;
""".strip()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = parse_args()
    config = PipelineConfig.load(args.config)
    client = create_bigquery_client(config.project_id)
    dry_run_script = build_lint_script(config)
    client.query(dry_run_script, job_config=bigquery.QueryJobConfig(dry_run=True, use_query_cache=False))
    logging.getLogger(__name__).info("BigQuery dry-run lint succeeded for %s.", args.config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
