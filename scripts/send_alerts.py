from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from mdmc_platform.alerts import dispatch_alerts
from mdmc_platform.config import PipelineConfig


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dispatch pipeline alerts from a quality report.")
    parser.add_argument("--config", required=True, help="Path to the deployment config.")
    parser.add_argument("--quality-report", default="artifacts/quality_report.json", help="Path to quality_report.json.")
    parser.add_argument(
        "--pipeline-status",
        required=True,
        choices=("success", "failure", "cancelled", "skipped"),
        help="Outcome of the pipeline step in GitHub Actions.",
    )
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = parse_args()
    config = PipelineConfig.load(args.config, project_id="alerting-only")
    decision = dispatch_alerts(
        config,
        report_path=args.quality_report,
        pipeline_status=args.pipeline_status,
    )
    logging.getLogger(__name__).info(
        "Alert decision for %s: should_alert=%s clean=%s items=%s",
        config.client.id,
        decision.should_alert,
        decision.is_clean,
        len(decision.items),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
