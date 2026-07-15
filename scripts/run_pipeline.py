from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from mdmc_platform.auth import create_bigquery_client
from mdmc_platform.config import PipelineConfig
from mdmc_platform.connectors import build_connector
from mdmc_platform.quality_checks import run_quality_checks
from mdmc_platform.transform import run_transforms
from mdmc_platform.warehouse import BigQueryWarehouse


LOGGER = logging.getLogger(__name__)


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
        results, has_critical_failures = run_quality_checks(warehouse, config, built_marts)
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


if __name__ == "__main__":
    raise SystemExit(main())
