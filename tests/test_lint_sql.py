from __future__ import annotations

import pytest

from mdmc_platform.config import PipelineConfig
from mdmc_platform.transform import build_booking_window_sql
from scripts.lint_sql import (
    MART_FIXTURE_SQL,
    build_lint_context,
    build_lint_queries,
    dry_run_queries,
    strip_create_prefix,
)
from tests.test_schema_contract import MART_SCHEMA_CONTRACT, _output_columns


def test_strip_create_prefix_returns_query_body() -> None:
    sql = "CREATE OR REPLACE TABLE `demo.table` AS\nSELECT 1"
    assert strip_create_prefix(sql) == "SELECT 1"


def test_lint_builds_five_independent_pure_select_queries(monkeypatch) -> None:
    monkeypatch.setenv("GCP_PROJECT_ID", "demo-project")
    config = PipelineConfig.load("configs/demo.yaml")

    queries = build_lint_queries(config)

    assert set(queries) == {
        "daily_performance",
        "reconciliation",
        "booking_funnel",
        "kpi_summary",
        "ga4_extraction",
    }
    assert all("CREATE TEMP TABLE" not in query for query in queries.values())
    assert all("CREATE OR REPLACE TABLE" not in query for query in queries.values())
    assert "`lint_daily_performance`" not in queries["booking_funnel"]
    assert "`lint_reconciliation`" not in queries["kpi_summary"]
    assert "bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*" in queries["ga4_extraction"]


def test_lint_fixtures_match_frozen_mart_contract() -> None:
    assert set(MART_FIXTURE_SQL) == set(MART_SCHEMA_CONTRACT)
    for mart_name, fixture_sql in MART_FIXTURE_SQL.items():
        assert _output_columns(f"{fixture_sql}\nFROM (SELECT 1)") == MART_SCHEMA_CONTRACT[mart_name]


def test_lint_context_uses_shared_booking_window_builder(monkeypatch) -> None:
    monkeypatch.setenv("GCP_PROJECT_ID", "demo-project")
    config = PipelineConfig.load("configs/demo.yaml")

    context = build_lint_context(config)

    assert context["booking_window_sql"] == build_booking_window_sql(
        "lint_daily_performance",
        "lint_booking_funnel",
        config.transforms.rolling_window_days,
    )


def test_dry_run_reports_the_failing_model_name() -> None:
    class _Job:
        def result(self) -> None:
            return None

    class _Client:
        def query(self, query: str, job_config) -> _Job:
            del job_config
            if query == "SELECT broken":
                raise ValueError("bad SQL")
            return _Job()

    with pytest.raises(RuntimeError, match="BigQuery dry-run failed for reconciliation"):
        dry_run_queries(
            _Client(),
            {"daily_performance": "SELECT 1", "reconciliation": "SELECT broken"},
        )
