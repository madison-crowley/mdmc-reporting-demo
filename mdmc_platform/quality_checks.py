from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
import json

from mdmc_platform.config import PipelineConfig


DEFAULT_SEVERITIES = {
    "freshness": "CRITICAL",
    "daily_performance_row_count": "CRITICAL",
    "reconciliation_row_count": "CRITICAL",
    "booking_funnel_row_count": "CRITICAL",
    "kpi_summary_row_count": "CRITICAL",
    "daily_performance_nulls": "CRITICAL",
    "reconciliation_nulls": "CRITICAL",
    "booking_funnel_nulls": "CRITICAL",
    "spend_anomaly": "WARN",
    "reconciliation_flag_count": "WARN",
}

NULL_CHECK_COLUMNS = {
    "daily_performance": ("date", "platform", "campaign"),
    "reconciliation": ("date", "platform"),
    "booking_funnel": ("date",),
}


@dataclass(frozen=True)
class QualityCheckResult:
    check: str
    severity: str
    value: object
    threshold: object
    passed: bool


def _normalize_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(str(value))


def _severity_for(config: PipelineConfig, check_name: str) -> str:
    return config.quality.severity_overrides.get(check_name, DEFAULT_SEVERITIES[check_name])


def _check_threshold(config: PipelineConfig, check_name: str, key: str, default: int) -> int:
    settings = config.quality.checks.get(check_name, {})
    raw_value = settings.get(key, default)
    if not isinstance(raw_value, int) or isinstance(raw_value, bool):
        raise ValueError(f"quality.checks.{check_name}.{key} must be an integer.")
    return raw_value


def _discover_available_marts(warehouse, config: PipelineConfig) -> tuple[str, ...]:
    marts = []
    for mart_name in ("daily_performance", "reconciliation", "booking_funnel", "kpi_summary"):
        if warehouse.table_exists(config.mart_table_fqn(mart_name)):
            marts.append(mart_name)
    return tuple(marts)


def evaluate_freshness(max_date: date | None, expected_date: date, max_lag_days: int) -> tuple[int | None, bool]:
    if max_date is None:
        return None, False
    lag_days = (expected_date - max_date).days
    return lag_days, bool(0 <= lag_days <= max_lag_days)


def run_quality_checks(warehouse, config: PipelineConfig, built_marts: tuple[str, ...] | None = None) -> tuple[list[QualityCheckResult], bool]:
    resolved_marts = built_marts or _discover_available_marts(warehouse, config)
    results: list[QualityCheckResult] = []

    if "daily_performance" in resolved_marts:
        max_date = _normalize_date(
            warehouse.query_scalar(
                f"SELECT MAX(date) AS max_date FROM `{config.mart_table_fqn('daily_performance')}`",
                "max_date",
            )
        )
        expected_date = date.today() - timedelta(days=1)
        max_lag_days = _check_threshold(config, "freshness", "max_lag_days", 0)
        lag_days, passed = evaluate_freshness(max_date, expected_date, max_lag_days)
        results.append(
            QualityCheckResult(
                check="freshness",
                severity=_severity_for(config, "freshness"),
                value=max_date.isoformat() if max_date else None,
                threshold={"expected_date": expected_date.isoformat(), "max_lag_days": max_lag_days},
                passed=passed,
            )
        )

    for mart_name in resolved_marts:
        row_count_check = f"{mart_name}_row_count"
        if row_count_check in DEFAULT_SEVERITIES:
            min_rows = _check_threshold(config, row_count_check, "min_rows", 1)
            row_count = warehouse.query_scalar(
                f"SELECT COUNT(*) AS row_count FROM `{config.mart_table_fqn(mart_name)}`",
                "row_count",
            )
            results.append(
                QualityCheckResult(
                    check=row_count_check,
                    severity=_severity_for(config, row_count_check),
                    value=row_count,
                    threshold=min_rows,
                    passed=bool(row_count >= min_rows),
                )
            )

    for mart_name, columns in NULL_CHECK_COLUMNS.items():
        if mart_name not in resolved_marts:
            continue
        check_name = f"{mart_name}_nulls"
        condition = " OR ".join(f"{column} IS NULL" for column in columns)
        null_rows = warehouse.query_scalar(
            f"SELECT COUNT(*) AS null_rows FROM `{config.mart_table_fqn(mart_name)}` WHERE {condition}",
            "null_rows",
        )
        results.append(
            QualityCheckResult(
                check=check_name,
                severity=_severity_for(config, check_name),
                value=null_rows,
                threshold=0,
                passed=bool(null_rows == 0),
            )
        )

    if "daily_performance" in resolved_marts:
        stddev_multiplier = _check_threshold(config, "spend_anomaly", "stddev_multiplier", 2)
        spend_anomalies = warehouse.query_scalar(
            f"""
WITH spend_by_day AS (
  SELECT date, SUM(spend) AS spend
  FROM `{config.mart_table_fqn('daily_performance')}`
  GROUP BY 1
),
scored AS (
  SELECT
    date,
    spend,
    AVG(spend) OVER (ORDER BY date ROWS BETWEEN {config.transforms.rolling_window_days - 1} PRECEDING AND 1 PRECEDING) AS rolling_avg,
    STDDEV_POP(spend) OVER (ORDER BY date ROWS BETWEEN {config.transforms.rolling_window_days - 1} PRECEDING AND 1 PRECEDING) AS rolling_stddev
  FROM spend_by_day
)
SELECT COUNTIF(
  rolling_avg IS NOT NULL
  AND rolling_stddev IS NOT NULL
  AND spend > rolling_avg + ({stddev_multiplier} * rolling_stddev)
) AS anomaly_count
FROM scored
""",
            "anomaly_count",
        )
        results.append(
            QualityCheckResult(
                check="spend_anomaly",
                severity=_severity_for(config, "spend_anomaly"),
                value=spend_anomalies,
                threshold=0,
                passed=bool(spend_anomalies == 0),
            )
        )

    if "reconciliation" in resolved_marts:
        max_warn_flags = _check_threshold(config, "reconciliation_flag_count", "max_warn_flags", 0)
        flag_count = warehouse.query_scalar(
            f"SELECT COUNTIF(is_flagged) AS flag_count FROM `{config.mart_table_fqn('reconciliation')}`",
            "flag_count",
        )
        results.append(
            QualityCheckResult(
                check="reconciliation_flag_count",
                severity=_severity_for(config, "reconciliation_flag_count"),
                value=flag_count,
                threshold=max_warn_flags,
                passed=bool(flag_count <= max_warn_flags),
            )
        )

    artifacts_dir = Path("artifacts")
    artifacts_dir.mkdir(exist_ok=True)
    report_path = artifacts_dir / "quality_report.json"
    report_path.write_text(
        json.dumps(
            {
                "generated_at": datetime.utcnow().isoformat() + "Z",
                "checks": [asdict(result) for result in results],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    has_critical_failures = any(result.severity == "CRITICAL" and not result.passed for result in results)
    return results, has_critical_failures
