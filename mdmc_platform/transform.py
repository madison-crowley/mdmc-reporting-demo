from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from string import Template

from mdmc_platform.config import PipelineConfig
from mdmc_platform.connectors.base import ExtractResult


SQL_DIR = Path(__file__).resolve().parents[1] / "sql"
ALL_MARTS = ("daily_performance", "reconciliation", "booking_funnel", "kpi_summary")


@dataclass(frozen=True)
class TransformResult:
    built_marts: tuple[str, ...]
    skipped_marts: tuple[str, ...]


def build_union_sql(table_fqns: list[str]) -> str:
    return "\nUNION ALL\n".join(f"SELECT * FROM `{table_fqn}`" for table_fqn in table_fqns)


def build_source_date_union_sql(table_fqns: list[str]) -> str:
    return "\nUNION ALL\n".join(f"SELECT source_date FROM `{table_fqn}`" for table_fqn in table_fqns)


def render_sql_template(template_name: str, context: dict[str, str]) -> str:
    template = Template((SQL_DIR / f"{template_name}.sql").read_text(encoding="utf-8"))
    return template.substitute(context)


def planned_marts(categories_present: set[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    built: list[str] = []
    skipped: list[str] = []
    can_build_performance = {"web_analytics", "ad_platform"}.issubset(categories_present)
    has_booking_system = "booking_system" in categories_present

    if can_build_performance:
        built.extend(["daily_performance", "reconciliation", "kpi_summary"])
    else:
        skipped.extend(["daily_performance", "reconciliation", "kpi_summary"])

    if can_build_performance and has_booking_system:
        built.append("booking_funnel")
    else:
        skipped.append("booking_funnel")
    return tuple(built), tuple(skipped)


def _empty_booking_window_sql() -> str:
    return """
SELECT
  CAST(NULL AS INT64) AS appointments_booked,
  CAST(NULL AS INT64) AS no_shows
"""


def run_transforms(warehouse, config: PipelineConfig, extracts: list[ExtractResult]) -> TransformResult:
    category_tables: dict[str, list[str]] = {}
    for extract in extracts:
        category_tables.setdefault(extract.source_category, [])
        category_tables[extract.source_category].extend(table.table_fqn for table in extract.tables)

    categories_present = set(category_tables)
    built_marts, skipped_marts = planned_marts(categories_present)
    if not built_marts:
        return TransformResult(built_marts=tuple(), skipped_marts=skipped_marts)

    all_source_tables = [table for tables in category_tables.values() for table in tables]
    base_context = {
        "daily_performance_table": config.mart_table_fqn("daily_performance"),
        "reconciliation_table": config.mart_table_fqn("reconciliation"),
        "booking_funnel_table": config.mart_table_fqn("booking_funnel"),
        "kpi_summary_table": config.mart_table_fqn("kpi_summary"),
        "web_analytics_union_sql": build_union_sql(category_tables.get("web_analytics", [])),
        "ad_platform_union_sql": build_union_sql(category_tables.get("ad_platform", [])),
        "booking_system_union_sql": build_union_sql(category_tables.get("booking_system", [])),
        "max_source_date_union_sql": build_source_date_union_sql(all_source_tables),
        "date_shift_enabled": "TRUE" if config.transforms.date_shift else "FALSE",
        "reconciliation_threshold_pct": str(config.transforms.reconciliation_threshold_pct),
        "rolling_window_days": str(config.transforms.rolling_window_days),
        "rolling_window_days_minus_one": str(config.transforms.rolling_window_days - 1),
        "booking_window_sql": (
            f"SELECT SUM(appointments_booked) AS appointments_booked, SUM(no_shows) AS no_shows "
            f"FROM `{config.mart_table_fqn('booking_funnel')}` "
            f"WHERE date >= DATE_SUB((SELECT MAX(date) FROM `{config.mart_table_fqn('daily_performance')}`), "
            f"INTERVAL {config.transforms.rolling_window_days - 1} DAY)"
            if "booking_funnel" in built_marts
            else _empty_booking_window_sql()
        ),
    }

    execution_order = [mart for mart in ALL_MARTS if mart in built_marts]
    for mart in execution_order:
        sql = render_sql_template(mart, base_context)
        warehouse.run_sql(sql)
    return TransformResult(built_marts=built_marts, skipped_marts=skipped_marts)
