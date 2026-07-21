from __future__ import annotations

import argparse
from datetime import datetime, timezone
import logging
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from mdmc_platform.auth import create_bigquery_client
from mdmc_platform.config import ConfigValidationError
from mdmc_platform.config import PipelineConfig
from mdmc_platform.connectors import build_connector
from mdmc_platform.quality_checks import build_pipeline_failure_result, run_quality_checks, write_quality_report
from mdmc_platform.transform import run_transforms
from mdmc_platform.warehouse import BigQueryWarehouse


LOGGER = logging.getLogger(__name__)


def build_extraction_metadata(warehouse, extract_result) -> dict[str, object]:
    tables = []
    rows_loaded = 0
    for table in extract_result.tables:
        row_count = int(
            warehouse.query_scalar(
                f"SELECT COUNT(*) AS row_count FROM `{table.table_fqn}`",
                "row_count",
            )
        )
        rows_loaded += row_count
        tables.append({"table_fqn": table.table_fqn, "rows_loaded": row_count})
    return {
        "source_name": extract_result.source_name,
        "source_category": extract_result.source_category,
        "rows_loaded": rows_loaded,
        "tables": tables,
        "extracted_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the MDMC reporting platform pipeline.")
    parser.add_argument("--config", required=True, help="Path to a client deployment YAML config.")
    parser.add_argument(
        "--step",
        default="all",
        choices=("all", "extract", "transform", "checks"),
        help="Pipeline step to run.",
    )
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = parse_args()
    config: PipelineConfig | None = None
    extraction_metadata: list[dict[str, object]] = []
    try:
        config = PipelineConfig.load(args.config)
        warehouse = BigQueryWarehouse(create_bigquery_client(config.project_id))
        warehouse.ensure_dataset(config.raw_dataset)
        warehouse.ensure_dataset(config.marts_dataset)

        extracts = []
        if args.step in {"all", "extract", "transform"}:
            LOGGER.info("Running extract step for client %s.", config.client.id)
            for source in config.sources:
                connector = build_connector(source, config)
                extract_result = connector.extract(warehouse, extracts)
                extracts.append(extract_result)
                extraction_metadata.append(build_extraction_metadata(warehouse, extract_result))
                LOGGER.info("Extracted %s via %s.", source.name, source.connector)

        transform_result = None
        if args.step in {"all", "transform"}:
            LOGGER.info("Running transform step.")
            transform_result = run_transforms(warehouse, config, extracts)
            LOGGER.info("Built marts: %s", ", ".join(transform_result.built_marts) or "none")
            if transform_result.skipped_marts:
                LOGGER.info("Skipped marts: %s", ", ".join(transform_result.skipped_marts))

        if args.step in {"all", "checks"}:
            LOGGER.info("Running quality checks.")
            built_marts = transform_result.built_marts if transform_result else None
            results, has_critical_failures = run_quality_checks(
                warehouse,
                config,
                built_marts,
                extracts=extracts if args.step == "all" else None,
                require_current_run_marts=args.step == "all",
                report_metadata={"extractions": extraction_metadata},
            )
            for result in results:
                LOGGER.info(
                    "Check %-30s severity=%s passed=%s value=%s threshold=%s",
                    result.check,
                    result.severity,
                    result.passed,
                    result.value,
                    result.threshold,
                )
            if has_critical_failures:
                LOGGER.error("Critical quality checks failed.")
                return 1
        return 0
    except Exception as exc:
        if isinstance(exc, ConfigValidationError):
            LOGGER.error("Config validation failed: %s", exc)
        else:
            LOGGER.exception("Pipeline execution failed.")
        write_quality_report(
            config,
            [build_pipeline_failure_result(str(exc))],
            pipeline_status="failed",
            metadata={"extractions": extraction_metadata},
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
