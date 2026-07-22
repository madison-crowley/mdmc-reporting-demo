from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
import json

from mdmc_platform.config import PipelineConfig
from mdmc_platform.connectors import CONNECTOR_REGISTRY
from mdmc_platform.connectors.base import ExtractResult
from mdmc_platform.transform import build_union_sql, planned_marts


DEFAULT_SEVERITIES = {
    "presentation_alignment": "CRITICAL",
    "expected_marts_built": "CRITICAL",
    "source_watermark_divergence": "WARN",
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


def write_quality_report(
    config: PipelineConfig | None,
    results: list[QualityCheckResult],
    *,
    output_path: Path | None = None,
    pipeline_status: str = "success",
    metadata: dict[str, object] | None = None,
) -> Path:
    artifacts_dir = Path("artifacts")
    artifacts_dir.mkdir(exist_ok=True)
    report_path = output_path or (artifacts_dir / "quality_report.json")
    report_path.write_text(
        json.dumps(
            {
                "generated_at": datetime.utcnow().isoformat() + "Z",
                "client_id": config.client.id if config is not None else None,
                "pipeline_status": pipeline_status,
                "metadata": metadata or {},
                "checks": [asdict(result) for result in results],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return report_path


def build_pipeline_failure_result(message: str) -> QualityCheckResult:
    return QualityCheckResult(
        check="pipeline_execution",
        severity="CRITICAL",
        value=message,
        threshold="successful pipeline execution",
        passed=False,
    )


def load_quality_report(path: str | Path) -> dict[str, object]:
    report_path = Path(path)
    if not report_path.exists():
        return {
            "generated_at": None,
            "client_id": None,
            "pipeline_status": "missing",
            "metadata": {},
            "checks": [],
        }
    return json.loads(report_path.read_text(encoding="utf-8"))


def _normalize_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
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


def configured_source_categories(config: PipelineConfig) -> set[str]:
    categories: set[str] = set()
    for source in config.sources:
        connector_class = CONNECTOR_REGISTRY.get(source.connector)
        if connector_class is not None:
            categories.add(connector_class.source_category)
    return categories


def expected_marts_for_config(config: PipelineConfig) -> tuple[str, ...]:
    expected, _ = planned_marts(configured_source_categories(config))
    return expected


def build_expected_marts_result(
    config: PipelineConfig,
    built_marts: tuple[str, ...],
) -> QualityCheckResult:
    expected_marts = expected_marts_for_config(config)
    missing_marts = [mart for mart in expected_marts if mart not in built_marts]
    return QualityCheckResult(
        check="expected_marts_built",
        severity=_severity_for(config, "expected_marts_built"),
        value={"built": list(built_marts), "missing": missing_marts},
        threshold={"expected": list(expected_marts)},
        passed=not missing_marts,
    )


def evaluate_presentation_alignment(
    max_date: date | None,
    expected_date: date,
    max_lag_days: int,
) -> tuple[int | None, bool]:
    if max_date is None:
        return None, False
    lag_days = (expected_date - max_date).days
    return lag_days, bool(0 <= lag_days <= max_lag_days)


def _source_max_dates(
    warehouse,
    extracts: list[ExtractResult] | None,
) -> tuple[dict[str, date | None], dict[str, date | None]]:
    raw_source_max_dates: dict[str, date | None] = {}
    source_categories: dict[str, str] = {}
    for extract in extracts or []:
        table_fqns = [table.table_fqn for table in extract.tables]
        max_date = warehouse.query_scalar(
            f"SELECT MAX(source_date) AS max_date FROM (\n{build_union_sql(table_fqns)}\n)",
            "max_date",
        )
        raw_source_max_dates[extract.source_name] = _normalize_date(max_date)
        source_categories[extract.source_name] = extract.source_category

    raw_category_max_dates: dict[str, date | None] = {}
    for source_name, source_category in source_categories.items():
        source_max = raw_source_max_dates[source_name]
        current_max = raw_category_max_dates.get(source_category)
        if source_max is not None and (current_max is None or source_max > current_max):
            raw_category_max_dates[source_category] = source_max
        else:
            raw_category_max_dates.setdefault(source_category, None)

    # The common watermark is defined on observed source maxima, not the wall clock.
    return raw_source_max_dates, raw_category_max_dates


def _window_bounds(
    warehouse,
    config: PipelineConfig,
    resolved_marts: tuple[str, ...],
    source_max_dates: dict[str, date | None],
) -> tuple[date | None, date | None]:
    required_categories = configured_source_categories(config)
    if required_categories and required_categories <= set(source_max_dates):
        maxima = [source_max_dates[category] for category in required_categories]
        if all(maximum is not None for maximum in maxima):
            window_end = min(maximum for maximum in maxima if maximum is not None)
            return window_end - timedelta(days=config.transforms.rolling_window_days - 1), window_end

    if "kpi_summary" in resolved_marts:
        window_start = _normalize_date(
            warehouse.query_scalar(
                f"SELECT window_start FROM `{config.mart_table_fqn('kpi_summary')}` LIMIT 1",
                "window_start",
            )
        )
        window_end = _normalize_date(
            warehouse.query_scalar(
                f"SELECT window_end FROM `{config.mart_table_fqn('kpi_summary')}` LIMIT 1",
                "window_end",
            )
        )
        return window_start, window_end
    return None, None


def _spend_anomaly_query(
    config: PipelineConfig,
    stddev_multiplier: int,
    *,
    window_start: date | None = None,
    window_end: date | None = None,
) -> str:
    window_filter = ""
    if window_start is not None and window_end is not None:
        window_filter = f"\nWHERE date BETWEEN DATE '{window_start.isoformat()}' AND DATE '{window_end.isoformat()}'"
    return f"""
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
FROM scored{window_filter}
"""


def run_quality_checks(
    warehouse,
    config: PipelineConfig,
    built_marts: tuple[str, ...] | None = None,
    *,
    extracts: list[ExtractResult] | None = None,
    require_current_run_marts: bool = False,
    report_metadata: dict[str, object] | None = None,
) -> tuple[list[QualityCheckResult], bool]:
    resolved_marts = _discover_available_marts(warehouse, config) if built_marts is None else built_marts
    results: list[QualityCheckResult] = []
    metadata = dict(report_metadata or {})

    if require_current_run_marts:
        results.append(build_expected_marts_result(config, resolved_marts))

    source_max_dates, source_category_max_dates = _source_max_dates(warehouse, extracts)
    window_start, window_end = _window_bounds(
        warehouse,
        config,
        resolved_marts,
        source_category_max_dates,
    )
    metadata["window_start"] = window_start.isoformat() if window_start else None
    metadata["window_end"] = window_end.isoformat() if window_end else None
    metadata["source_max_dates"] = {
        source_name: maximum.isoformat() if maximum else None
        for source_name, maximum in sorted(source_max_dates.items())
    }
    metadata["source_category_max_dates"] = {
        category: maximum.isoformat() if maximum else None
        for category, maximum in sorted(source_category_max_dates.items())
    }

    required_categories = configured_source_categories(config)
    required_maxima = [source_category_max_dates.get(category) for category in required_categories]
    divergence_days: int | None = None
    if required_maxima and all(maximum is not None for maximum in required_maxima):
        normalized_maxima = [maximum for maximum in required_maxima if maximum is not None]
        divergence_days = (max(normalized_maxima) - min(normalized_maxima)).days
    if extracts is not None:
        results.append(
            QualityCheckResult(
                check="source_watermark_divergence",
                severity=_severity_for(config, "source_watermark_divergence"),
                value=divergence_days,
                threshold={"max_divergence_days": 1},
                passed=bool(divergence_days is not None and divergence_days <= 1),
            )
        )

    if "daily_performance" in resolved_marts:
        max_date = _normalize_date(
            warehouse.query_scalar(
                f"SELECT MAX(date) AS max_date FROM `{config.mart_table_fqn('daily_performance')}`",
                "max_date",
            )
        )
        expected_date = date.today() - timedelta(days=1)
        max_lag_days = _check_threshold(config, "presentation_alignment", "max_lag_days", 0)
        _, passed = evaluate_presentation_alignment(max_date, expected_date, max_lag_days)
        results.append(
            QualityCheckResult(
                check="presentation_alignment",
                severity=_severity_for(config, "presentation_alignment"),
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

    historical_totals: dict[str, object] = {}
    if "daily_performance" in resolved_marts:
        stddev_multiplier = _check_threshold(config, "spend_anomaly", "stddev_multiplier", 2)
        spend_anomalies = warehouse.query_scalar(
            _spend_anomaly_query(
                config,
                stddev_multiplier,
                window_start=window_start,
                window_end=window_end,
            ),
            "anomaly_count",
        )
        historical_totals["spend_anomaly"] = warehouse.query_scalar(
            _spend_anomaly_query(config, stddev_multiplier),
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
        window_filter = ""
        if window_start is not None and window_end is not None:
            window_filter = (
                f" WHERE date BETWEEN DATE '{window_start.isoformat()}' "
                f"AND DATE '{window_end.isoformat()}'"
            )
        flag_count = warehouse.query_scalar(
            f"SELECT COUNTIF(is_flagged) AS flag_count "
            f"FROM `{config.mart_table_fqn('reconciliation')}`{window_filter}",
            "flag_count",
        )
        historical_totals["reconciliation_flag_count"] = warehouse.query_scalar(
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

    metadata["historical_totals"] = historical_totals
    has_critical_failures = any(result.severity == "CRITICAL" and not result.passed for result in results)
    write_quality_report(
        config,
        results,
        pipeline_status="failed" if has_critical_failures else "success",
        metadata=metadata,
    )
    return results, has_critical_failures
