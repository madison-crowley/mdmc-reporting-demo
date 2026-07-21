from __future__ import annotations

import argparse
from dataclasses import dataclass
import logging
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from mdmc_platform.alerts import dispatch_alerts
from mdmc_platform.config import PipelineConfig
import yaml


@dataclass(frozen=True)
class _FallbackClient:
    id: str


@dataclass(frozen=True)
class _FallbackAlerts:
    github_issues: bool = True
    slack_webhook_env: str | None = None


@dataclass(frozen=True)
class FallbackAlertConfig:
    client: _FallbackClient
    alerts: _FallbackAlerts


def load_alert_config(config_path: str | Path, fallback_client_id: str = "unknown") -> PipelineConfig | FallbackAlertConfig:
    try:
        return PipelineConfig.load(config_path, project_id="alerting-only")
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "Deployment config could not be validated for alert dispatch; using fallback identity: %s",
            exc,
        )

    client_id = fallback_client_id
    slack_webhook_env: str | None = None
    try:
        payload = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
        if isinstance(payload, dict):
            client_block = payload.get("client")
            if isinstance(client_block, dict) and isinstance(client_block.get("id"), str):
                client_id = client_block["id"].strip() or fallback_client_id
            alerts_block = payload.get("alerts")
            if isinstance(alerts_block, dict) and isinstance(alerts_block.get("slack_webhook_env"), str):
                slack_webhook_env = alerts_block["slack_webhook_env"].strip() or None
    except Exception:
        pass
    return FallbackAlertConfig(
        client=_FallbackClient(client_id),
        alerts=_FallbackAlerts(slack_webhook_env=slack_webhook_env),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dispatch pipeline alerts from a quality report.")
    parser.add_argument("--config", required=True, help="Path to the deployment config.")
    parser.add_argument("--quality-report", default="artifacts/quality_report.json", help="Path to quality_report.json.")
    parser.add_argument(
        "--client-id",
        default="unknown",
        help="Fallback client id when the deployment config cannot be parsed.",
    )
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
    config = load_alert_config(args.config, args.client_id)
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
