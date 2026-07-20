from __future__ import annotations

import re

import pytest

from mdmc_platform.transform import render_sql_template


MART_SCHEMA_CONTRACT = {
    "daily_performance": [
        "date",
        "platform",
        "campaign",
        "spend",
        "clicks",
        "impressions",
        "ga4_sessions",
        "ga4_purchases",
        "ga4_revenue",
        "platform_conversions",
        "cpa",
        "roas",
    ],
    "reconciliation": [
        "date",
        "platform",
        "ga4_purchases",
        "platform_conversions",
        "absolute_discrepancy",
        "discrepancy_pct",
        "is_flagged",
    ],
    "booking_funnel": [
        "date",
        "spend",
        "ga4_sessions",
        "appointments_booked",
        "appointments_completed",
        "no_shows",
        "booking_revenue",
        "cost_per_booking",
        "revenue_per_spend_dollar",
    ],
    "kpi_summary": [
        "rolling_window_days",
        "window_start",
        "window_end",
        "spend",
        "clicks",
        "impressions",
        "ga4_sessions",
        "ga4_purchases",
        "ga4_revenue",
        "platform_conversions",
        "cost_per_booking",
        "no_show_rate",
        "reconciliation_flag_count",
    ],
}


RENDER_CONTEXT = {
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
}


def _final_select_items(sql: str) -> list[str]:
    depth = 0
    final_select_start: int | None = None
    for match in re.finditer(r"\bSELECT\b|[()]", sql, flags=re.IGNORECASE):
        token = match.group(0).upper()
        if token == "(":
            depth += 1
        elif token == ")":
            depth -= 1
        elif depth == 0:
            final_select_start = match.end()

    if final_select_start is None:
        raise AssertionError("Rendered mart SQL has no top-level SELECT.")

    depth = 0
    final_select_end: int | None = None
    for match in re.finditer(r"\bFROM\b|[()]", sql[final_select_start:], flags=re.IGNORECASE):
        token = match.group(0).upper()
        if token == "(":
            depth += 1
        elif token == ")":
            depth -= 1
        elif depth == 0:
            final_select_end = final_select_start + match.start()
            break

    if final_select_end is None:
        raise AssertionError("Rendered mart SQL final SELECT has no FROM clause.")

    projection = sql[final_select_start:final_select_end]
    items: list[str] = []
    item_start = 0
    depth = 0
    for index, character in enumerate(projection):
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        elif character == "," and depth == 0:
            items.append(projection[item_start:index].strip())
            item_start = index + 1
    items.append(projection[item_start:].strip())
    return items


def _output_columns(sql: str) -> list[str]:
    columns: list[str] = []
    for item in _final_select_items(sql):
        alias = re.search(r"\bAS\s+`?([A-Za-z_][A-Za-z0-9_]*)`?\s*$", item, flags=re.IGNORECASE)
        if alias:
            columns.append(alias.group(1))
            continue
        implicit_name = re.search(r"`?([A-Za-z_][A-Za-z0-9_]*)`?\s*$", item)
        if not implicit_name:
            raise AssertionError(f"Final projection has no stable output name: {item}")
        columns.append(implicit_name.group(1))
    return columns


@pytest.mark.parametrize("mart_name", MART_SCHEMA_CONTRACT)
def test_rendered_mart_schema_matches_frozen_contract(mart_name: str) -> None:
    rendered_sql = render_sql_template(mart_name, RENDER_CONTEXT)

    assert _output_columns(rendered_sql) == MART_SCHEMA_CONTRACT[mart_name]
