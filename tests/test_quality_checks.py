from __future__ import annotations

from datetime import date
from pathlib import Path

from mdmc_platform.config import (
    AlertSettings,
    ClientSettings,
    PipelineConfig,
    QualitySettings,
    SourceConfig,
    TransformSettings,
    WarehouseSettings,
)
from mdmc_platform.connectors.base import ExtractedTable, ExtractResult
from mdmc_platform.quality_checks import (
    build_expected_marts_result,
    evaluate_presentation_alignment,
    expected_marts_for_config,
    run_quality_checks,
)


def _config(*connectors: str) -> PipelineConfig:
    return PipelineConfig(
        project_id="demo-project",
        client=ClientSettings(id="demo", display_name="Demo"),
        warehouse=WarehouseSettings(dataset_prefix="demo"),
        sources=tuple(
            SourceConfig(name=f"source-{index}", connector=connector)
            for index, connector in enumerate(connectors)
        ),
        transforms=TransformSettings(
            date_shift=True,
            reconciliation_threshold_pct=8,
            rolling_window_days=28,
        ),
        quality=QualitySettings(
            checks={
                "presentation_alignment": {"max_lag_days": 0},
                "reconciliation_row_count": {"min_rows": 1},
                "reconciliation_flag_count": {"max_warn_flags": 0},
            }
        ),
        alerts=AlertSettings(github_issues=True),
        config_path=Path("configs/demo.yaml"),
    )


def test_presentation_alignment_fails_when_max_date_is_in_the_future() -> None:
    lag_days, passed = evaluate_presentation_alignment(
        max_date=date(2026, 7, 16),
        expected_date=date(2026, 7, 15),
        max_lag_days=0,
    )

    assert lag_days == -1
    assert passed is False


def test_presentation_alignment_passes_when_max_date_matches_expected_date() -> None:
    lag_days, passed = evaluate_presentation_alignment(
        max_date=date(2026, 7, 15),
        expected_date=date(2026, 7, 15),
        max_lag_days=0,
    )

    assert lag_days == 0
    assert passed is True


def test_empty_built_marts_fails_current_run_contract(monkeypatch) -> None:
    config = _config("ga4_bigquery_sample", "synthetic_ads", "synthetic_bookings")
    monkeypatch.setattr("mdmc_platform.quality_checks.write_quality_report", lambda *args, **kwargs: Path("unused"))

    results, has_critical_failures = run_quality_checks(
        object(),
        config,
        built_marts=(),
        require_current_run_marts=True,
    )

    expected_result = next(result for result in results if result.check == "expected_marts_built")
    assert expected_result.passed is False
    assert set(expected_result.value["missing"]) == set(expected_marts_for_config(config))
    assert has_critical_failures is True


def test_missing_expected_mart_fails_contract() -> None:
    config = _config("ga4_bigquery_sample", "synthetic_ads", "synthetic_bookings")

    result = build_expected_marts_result(config, ("daily_performance", "reconciliation"))

    assert result.passed is False
    assert set(result.value["missing"]) == {"booking_funnel", "kpi_summary"}


def test_partial_source_categories_expect_correct_mart_subset() -> None:
    assert expected_marts_for_config(_config("ga4_bigquery_sample")) == ()
    assert expected_marts_for_config(
        _config("ga4_bigquery_sample", "synthetic_ads")
    ) == ("daily_performance", "reconciliation", "kpi_summary")
    assert expected_marts_for_config(
        _config("ga4_bigquery_sample", "synthetic_ads", "synthetic_bookings")
    ) == ("daily_performance", "reconciliation", "kpi_summary", "booking_funnel")


def test_reconciliation_alert_uses_common_window_and_preserves_historical_total(monkeypatch) -> None:
    config = _config("ga4_bigquery_sample", "synthetic_ads", "synthetic_bookings")
    queries: list[str] = []
    captured_report: dict[str, object] = {}

    class _Warehouse:
        def query_scalar(self, sql: str, field_name: str):
            queries.append(sql)
            if "MAX(source_date)" in sql:
                if "demo.raw.web" in sql:
                    return date(2026, 7, 20)
                if "demo.raw.ads" in sql:
                    return date(2026, 7, 19)
                return date(2026, 7, 20)
            if field_name == "row_count":
                return 100
            if field_name == "null_rows":
                return 0
            if field_name == "flag_count":
                return 2 if "WHERE date BETWEEN" in sql else 99
            raise AssertionError(f"Unexpected query: {sql}")

    extracts = [
        ExtractResult("web", "web_analytics", (ExtractedTable("web", "web_analytics", "web", "demo.raw.web"),)),
        ExtractResult("ads", "ad_platform", (ExtractedTable("ads", "ad_platform", "ads", "demo.raw.ads"),)),
        ExtractResult("bookings", "booking_system", (ExtractedTable("bookings", "booking_system", "bookings", "demo.raw.bookings"),)),
    ]

    def _capture_report(config, results, **kwargs):
        captured_report.update(kwargs.get("metadata", {}))
        return Path("unused")

    monkeypatch.setattr("mdmc_platform.quality_checks.write_quality_report", _capture_report)

    results, _ = run_quality_checks(
        _Warehouse(),
        config,
        built_marts=("reconciliation",),
        extracts=extracts,
    )

    flag_result = next(result for result in results if result.check == "reconciliation_flag_count")
    watermark_result = next(result for result in results if result.check == "source_watermark_divergence")
    assert flag_result.value == 2
    assert flag_result.passed is False
    assert watermark_result.value == 1
    assert watermark_result.severity == "WARN"
    assert watermark_result.passed is True
    assert captured_report["window_end"] == "2026-07-19"
    assert captured_report["window_start"] == "2026-06-22"
    assert captured_report["source_max_dates"] == {
        "ads": "2026-07-19",
        "bookings": "2026-07-20",
        "web": "2026-07-20",
    }
    assert captured_report["source_category_max_dates"]["ad_platform"] == "2026-07-19"
    assert captured_report["historical_totals"]["reconciliation_flag_count"] == 99
    assert any("COUNTIF(is_flagged)" in query and "WHERE date BETWEEN" in query for query in queries)
