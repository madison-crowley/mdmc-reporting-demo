from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import logging
import os
from pathlib import Path
from typing import Any
from urllib import error, request

from mdmc_platform.config import PipelineConfig
from mdmc_platform.quality_checks import build_pipeline_failure_result, load_quality_report


LOGGER = logging.getLogger(__name__)
PIPELINE_ALERT_LABEL = "pipeline-alert"


@dataclass(frozen=True)
class AlertCheck:
    check: str
    severity: str
    value: object
    threshold: object
    passed: bool


@dataclass(frozen=True)
class AlertDecision:
    should_alert: bool
    is_clean: bool
    items: tuple[AlertCheck, ...]
    report_date: str


def _parse_checks(report: dict[str, Any]) -> list[AlertCheck]:
    parsed: list[AlertCheck] = []
    for raw_item in report.get("checks", []):
        if not isinstance(raw_item, dict):
            continue
        parsed.append(
            AlertCheck(
                check=str(raw_item.get("check")),
                severity=str(raw_item.get("severity", "WARN")).upper(),
                value=raw_item.get("value"),
                threshold=raw_item.get("threshold"),
                passed=bool(raw_item.get("passed")),
            )
        )
    return parsed


def summarize_alerts(report: dict[str, Any], pipeline_status: str) -> AlertDecision:
    generated_at = str(report.get("generated_at") or (datetime.utcnow().isoformat() + "Z"))
    report_date = generated_at[:10]
    items = [item for item in _parse_checks(report) if not item.passed]
    if pipeline_status != "success" and not any(item.check == "pipeline_execution" for item in items):
        items.insert(0, AlertCheck(**build_pipeline_failure_result("Pipeline step exited nonzero.").__dict__))
    return AlertDecision(
        should_alert=bool(items),
        is_clean=pipeline_status == "success" and not items,
        items=tuple(items),
        report_date=report_date,
    )


def build_issue_title(client_id: str, report_date: str) -> str:
    return f"Pipeline alert — {client_id} — {report_date}"


def build_markdown_summary(client_id: str, pipeline_status: str, items: tuple[AlertCheck, ...]) -> str:
    lines = [
        f"# Pipeline alert for `{client_id}`",
        "",
        f"Pipeline status: `{pipeline_status}`",
        "",
        "| Check | Severity | Value | Threshold |",
        "| --- | --- | --- | --- |",
    ]
    for item in items:
        lines.append(f"| `{item.check}` | `{item.severity}` | `{item.value}` | `{item.threshold}` |")
    return "\n".join(lines)


def build_slack_summary(client_id: str, pipeline_status: str, items: tuple[AlertCheck, ...]) -> str:
    listed_checks = ", ".join(f"{item.check} ({item.severity})" for item in items[:5]) or "no failing checks listed"
    return f"MDMC pipeline alert for {client_id}: status={pipeline_status}. Checks: {listed_checks}"


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload).encode("utf-8")


def _github_request(method: str, url: str, token: str, payload: Any | None = None) -> Any:
    api_request = request.Request(
        url,
        data=None if payload is None else _json_bytes(payload),
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "mdmc-platform-alerts",
        },
        method=method,
    )
    with request.urlopen(api_request) as response:
        if response.status == 204:
            return None
        return json.loads(response.read().decode("utf-8"))


def ensure_label(repository: str, token: str) -> None:
    label_url = f"https://api.github.com/repos/{repository}/labels/{PIPELINE_ALERT_LABEL}"
    try:
        _github_request("GET", label_url, token)
    except error.HTTPError as exc:
        if exc.code != 404:
            raise
        _github_request(
            "POST",
            f"https://api.github.com/repos/{repository}/labels",
            token,
            {"name": PIPELINE_ALERT_LABEL, "color": "B60205", "description": "Automated pipeline alerts"},
        )


def list_open_pipeline_alert_issues(repository: str, token: str, client_id: str) -> list[dict[str, Any]]:
    issues = _github_request(
        "GET",
        f"https://api.github.com/repos/{repository}/issues?state=open&labels={PIPELINE_ALERT_LABEL}&per_page=100",
        token,
    )
    title_prefix = f"Pipeline alert — {client_id} — "
    return [issue for issue in issues if str(issue.get("title", "")).startswith(title_prefix)]


def create_or_update_issue(repository: str, token: str, client_id: str, title: str, body: str) -> None:
    ensure_label(repository, token)
    existing_issues = list_open_pipeline_alert_issues(repository, token, client_id)
    match = next((issue for issue in existing_issues if issue.get("title") == title), None)
    if match is not None:
        _github_request(
            "PATCH",
            f"https://api.github.com/repos/{repository}/issues/{match['number']}",
            token,
            {"body": body, "labels": [PIPELINE_ALERT_LABEL]},
        )
        return
    _github_request(
        "POST",
        f"https://api.github.com/repos/{repository}/issues",
        token,
        {"title": title, "body": body, "labels": [PIPELINE_ALERT_LABEL]},
    )


def close_open_pipeline_alert_issues(repository: str, token: str, client_id: str) -> None:
    for issue in list_open_pipeline_alert_issues(repository, token, client_id):
        _github_request(
            "POST",
            f"https://api.github.com/repos/{repository}/issues/{issue['number']}/comments",
            token,
            {"body": "Closing automatically: the latest pipeline run completed cleanly."},
        )
        _github_request(
            "PATCH",
            f"https://api.github.com/repos/{repository}/issues/{issue['number']}",
            token,
            {"state": "closed"},
        )


def post_slack_alert(webhook_url: str, text: str) -> None:
    slack_request = request.Request(
        webhook_url,
        data=_json_bytes({"text": text}),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(slack_request) as response:
        if response.status >= 400:
            raise RuntimeError(f"Slack webhook returned HTTP {response.status}.")


def dispatch_alerts(
    config: PipelineConfig,
    *,
    report_path: str | Path,
    pipeline_status: str,
    repository: str | None = None,
    github_token: str | None = None,
) -> AlertDecision:
    report = load_quality_report(report_path)
    decision = summarize_alerts(report, pipeline_status)

    if decision.should_alert:
        if config.alerts.github_issues:
            resolved_repository = repository or os.getenv("GITHUB_REPOSITORY")
            resolved_token = github_token or os.getenv("GITHUB_TOKEN")
            if not resolved_repository or not resolved_token:
                raise RuntimeError("GitHub issue alerting requires GITHUB_REPOSITORY and GITHUB_TOKEN.")
            create_or_update_issue(
                resolved_repository,
                resolved_token,
                config.client.id,
                build_issue_title(config.client.id, decision.report_date),
                build_markdown_summary(config.client.id, pipeline_status, decision.items),
            )

        if config.alerts.slack_webhook_env:
            webhook_url = os.getenv(config.alerts.slack_webhook_env)
            if webhook_url:
                post_slack_alert(
                    webhook_url,
                    build_slack_summary(config.client.id, pipeline_status, decision.items),
                )
            else:
                LOGGER.info("Slack webhook env %s is unset; skipping Slack alert.", config.alerts.slack_webhook_env)

    if decision.is_clean and config.alerts.github_issues:
        resolved_repository = repository or os.getenv("GITHUB_REPOSITORY")
        resolved_token = github_token or os.getenv("GITHUB_TOKEN")
        if not resolved_repository or not resolved_token:
            raise RuntimeError("GitHub issue closing requires GITHUB_REPOSITORY and GITHUB_TOKEN.")
        close_open_pipeline_alert_issues(resolved_repository, resolved_token, config.client.id)

    return decision
