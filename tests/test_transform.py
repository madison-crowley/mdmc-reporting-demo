from __future__ import annotations

from pathlib import Path

from mdmc_platform.transform import build_union_sql, planned_marts, render_sql_template


def test_build_union_sql_joins_all_tables() -> None:
    sql = build_union_sql(["demo.raw.table_a", "demo.raw.table_b"])
    assert "table_a" in sql
    assert "UNION ALL" in sql
    assert "table_b" in sql


def test_planned_marts_degrade_gracefully_without_booking_system() -> None:
    built, skipped = planned_marts({"web_analytics", "ad_platform"})
    assert built == ("daily_performance", "reconciliation", "kpi_summary")
    assert skipped == ("booking_funnel",)


def test_daily_performance_sql_renders_required_context() -> None:
    sql = render_sql_template(
        "daily_performance",
        {
            "daily_performance_table": "demo.demo_marts.daily_performance",
            "web_analytics_union_sql": "SELECT * FROM `demo.demo_raw.ga4`",
            "ad_platform_union_sql": "SELECT * FROM `demo.demo_raw.ads`",
            "max_source_date_union_sql": "SELECT source_date FROM `demo.demo_raw.ga4`",
            "date_shift_enabled": "TRUE",
            "reconciliation_threshold_pct": "10",
            "rolling_window_days": "28",
            "rolling_window_days_minus_one": "27",
            "reconciliation_table": "demo.demo_marts.reconciliation",
            "booking_funnel_table": "demo.demo_marts.booking_funnel",
            "kpi_summary_table": "demo.demo_marts.kpi_summary",
            "booking_system_union_sql": "SELECT * FROM `demo.demo_raw.bookings`",
            "booking_window_sql": "SELECT NULL AS appointments_booked, NULL AS no_shows",
        },
    )

    assert "CREATE OR REPLACE TABLE `demo.demo_marts.daily_performance`" in sql
    assert "DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)" in sql
    assert "demo.demo_raw.ga4" in sql
