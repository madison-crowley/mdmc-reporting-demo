from __future__ import annotations

from pathlib import Path

from mdmc_platform.transform import (
    build_booking_window_sql,
    build_union_sql,
    planned_marts,
    render_sql_template,
)


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


def test_kpi_summary_uses_web_analytics_union_for_ga4_totals_instead_of_daily_performance_duplicates() -> None:
    overlapping_daily_performance = [
        {"date": "2021-01-01", "platform": "Google Ads", "campaign": "Holiday Search", "ga4_sessions": 120, "ga4_purchases": 10, "ga4_revenue": 200.0},
        {"date": "2021-01-01", "platform": "Meta Ads", "campaign": "Holiday Search", "ga4_sessions": 120, "ga4_purchases": 10, "ga4_revenue": 200.0},
    ]
    naive_sessions_total = sum(row["ga4_sessions"] for row in overlapping_daily_performance)
    assert naive_sessions_total == 240

    sql = render_sql_template(
        "kpi_summary",
        {
            "daily_performance_table": "demo.demo_marts.daily_performance",
            "web_analytics_union_sql": "SELECT * FROM `demo.demo_raw.ga4`",
            "ad_platform_union_sql": "SELECT * FROM `demo.demo_raw.ads`",
            "max_source_date_union_sql": "SELECT source_date FROM `demo.demo_raw.ga4`",
            "date_shift_enabled": "TRUE",
            "reconciliation_threshold_pct": "8",
            "rolling_window_days": "28",
            "rolling_window_days_minus_one": "27",
            "reconciliation_table": "demo.demo_marts.reconciliation",
            "booking_funnel_table": "demo.demo_marts.booking_funnel",
            "kpi_summary_table": "demo.demo_marts.kpi_summary",
            "booking_system_union_sql": "SELECT * FROM `demo.demo_raw.bookings`",
            "booking_window_sql": "SELECT NULL AS appointments_booked, NULL AS no_shows",
        },
    )

    assert "web_analytics_window AS" in sql
    assert "FROM (\nSELECT * FROM `demo.demo_raw.ga4`" in sql
    assert "SUM(shifted_web_analytics.sessions) AS ga4_sessions" in sql
    assert "web_analytics_summary.ga4_sessions AS ga4_sessions" in sql


def test_booking_funnel_uses_all_web_analytics_sessions_for_daily_ga4_totals() -> None:
    sql = render_sql_template(
        "booking_funnel",
        {
            "daily_performance_table": "demo.demo_marts.daily_performance",
            "web_analytics_union_sql": "SELECT * FROM `demo.demo_raw.ga4`",
            "ad_platform_union_sql": "SELECT * FROM `demo.demo_raw.ads`",
            "max_source_date_union_sql": "SELECT source_date FROM `demo.demo_raw.ga4`",
            "date_shift_enabled": "TRUE",
            "reconciliation_threshold_pct": "8",
            "rolling_window_days": "28",
            "rolling_window_days_minus_one": "27",
            "reconciliation_table": "demo.demo_marts.reconciliation",
            "booking_funnel_table": "demo.demo_marts.booking_funnel",
            "kpi_summary_table": "demo.demo_marts.kpi_summary",
            "booking_system_union_sql": "SELECT * FROM `demo.demo_raw.bookings`",
            "booking_window_sql": "SELECT NULL AS appointments_booked, NULL AS no_shows",
        },
    )

    assert "web_analytics AS" in sql
    assert "sessions AS ga4_sessions" in sql
    assert "FROM `${daily_performance_table}`" not in sql.split("web_analytics AS", 1)[1].split("dates AS", 1)[0]


def test_booking_funnel_renders_no_shows_in_final_select() -> None:
    sql = render_sql_template(
        "booking_funnel",
        {
            "daily_performance_table": "demo.demo_marts.daily_performance",
            "web_analytics_union_sql": "SELECT * FROM `demo.demo_raw.ga4`",
            "ad_platform_union_sql": "SELECT * FROM `demo.demo_raw.ads`",
            "max_source_date_union_sql": "SELECT source_date FROM `demo.demo_raw.ga4`",
            "date_shift_enabled": "TRUE",
            "reconciliation_threshold_pct": "8",
            "rolling_window_days": "28",
            "rolling_window_days_minus_one": "27",
            "reconciliation_table": "demo.demo_marts.reconciliation",
            "booking_funnel_table": "demo.demo_marts.booking_funnel",
            "kpi_summary_table": "demo.demo_marts.kpi_summary",
            "booking_system_union_sql": "SELECT * FROM `demo.demo_raw.bookings`",
            "booking_window_sql": "SELECT NULL AS appointments_booked, NULL AS no_shows",
        },
    )

    assert "COALESCE(bookings.no_shows, 0) AS no_shows" in sql


def test_shared_booking_window_sql_builder_targets_real_tables() -> None:
    sql = build_booking_window_sql(
        "demo.demo_marts.daily_performance",
        "demo.demo_marts.booking_funnel",
        28,
    )

    assert "SUM(appointments_booked) AS appointments_booked" in sql
    assert "SUM(no_shows) AS no_shows" in sql
    assert "FROM `demo.demo_marts.booking_funnel`" in sql
    assert "MAX(date) FROM `demo.demo_marts.daily_performance`" in sql
