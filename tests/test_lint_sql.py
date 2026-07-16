from __future__ import annotations

from mdmc_platform.config import PipelineConfig
from scripts.lint_sql import build_lint_script, strip_create_prefix


def test_strip_create_prefix_returns_query_body() -> None:
    sql = "CREATE OR REPLACE TABLE `demo.table` AS\nSELECT 1"
    assert strip_create_prefix(sql) == "SELECT 1"


def test_lint_script_builds_temp_table_dry_run_script(monkeypatch) -> None:
    monkeypatch.setenv("GCP_PROJECT_ID", "demo-project")
    config = PipelineConfig.load("configs/demo.yaml")

    script = build_lint_script(config)

    assert "CREATE TEMP TABLE lint_daily_performance AS" in script
    assert "CREATE TEMP TABLE lint_kpi_summary AS" in script
    assert "SELECT 1;" in script
