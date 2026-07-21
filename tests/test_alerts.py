from __future__ import annotations

from pathlib import Path

from mdmc_platform.alerts import (
    build_issue_title,
    build_markdown_summary,
    create_or_update_issue,
    summarize_alerts,
)
from scripts.send_alerts import load_alert_config


def test_summarize_alerts_marks_warn_and_critical_failures_as_alertable() -> None:
    report = {
        "generated_at": "2026-07-16T07:00:00Z",
        "checks": [
            {"check": "presentation_alignment", "severity": "CRITICAL", "value": "2026-07-14", "threshold": "2026-07-15", "passed": False},
            {"check": "reconciliation_flag_count", "severity": "WARN", "value": 12, "threshold": 0, "passed": False},
        ],
    }

    decision = summarize_alerts(report, "failure")

    assert decision.should_alert is True
    assert decision.is_clean is False
    assert {item.check for item in decision.items} >= {"presentation_alignment", "reconciliation_flag_count"}


def test_summarize_alerts_injects_pipeline_execution_failure_when_report_has_no_failed_checks() -> None:
    decision = summarize_alerts({"generated_at": "2026-07-16T07:00:00Z", "checks": []}, "failure")

    assert decision.should_alert is True
    assert decision.items[0].check == "pipeline_execution"
    assert decision.items[0].severity == "CRITICAL"


def test_build_markdown_summary_and_title_are_client_specific() -> None:
    report = {
        "generated_at": "2026-07-16T07:00:00Z",
        "checks": [
            {"check": "presentation_alignment", "severity": "CRITICAL", "value": "late", "threshold": "today", "passed": False},
        ],
    }
    decision = summarize_alerts(report, "failure")

    title = build_issue_title("demo")
    body = build_markdown_summary("demo", "failure", decision.items, decision.report_date)

    assert title == "Pipeline alert — demo"
    assert "# Pipeline alert for `demo`" in body
    assert "Run date: `2026-07-16`" in body
    assert "| `presentation_alignment` | `CRITICAL` | `late` | `today` |" in body


def test_build_markdown_summary_escapes_pipes_and_newlines() -> None:
    report = {
        "generated_at": "2026-07-16T07:00:00Z",
        "checks": [
            {
                "check": "pipeline_execution",
                "severity": "CRITICAL",
                "value": "Unrecognized name: no_shows | field\nline 12",
                "threshold": "successful | execution\nonly",
                "passed": False,
            },
        ],
    }
    decision = summarize_alerts(report, "failure")

    body = build_markdown_summary("demo", "failure", decision.items)

    assert "Unrecognized name: no_shows \\| field<br>line 12" in body
    assert "successful \\| execution<br>only" in body


def test_continuing_incident_appends_a_comment_to_stable_issue(monkeypatch) -> None:
    calls: list[tuple[str, str, object]] = []
    monkeypatch.setattr("mdmc_platform.alerts.ensure_label", lambda repository, token: None)
    monkeypatch.setattr(
        "mdmc_platform.alerts.list_open_pipeline_alert_issues",
        lambda repository, token, client_id: [{"number": 17, "title": "Pipeline alert — demo"}],
    )
    monkeypatch.setattr(
        "mdmc_platform.alerts._github_request",
        lambda method, url, token, payload=None: calls.append((method, url, payload)),
    )

    create_or_update_issue("owner/repo", "token", "demo", "Pipeline alert — demo", "run summary")

    assert any(method == "PATCH" and payload == {"title": "Pipeline alert — demo", "labels": ["pipeline-alert"]} for method, _, payload in calls)
    assert any(method == "POST" and url.endswith("/issues/17/comments") and payload == {"body": "run summary"} for method, url, payload in calls)


def test_alert_config_fallback_uses_raw_yaml_client_id(tmp_path: Path) -> None:
    config_path = tmp_path / "invalid.yaml"
    config_path.write_text(
        """
client:
  id: fallback-demo
alerts:
  github_issues: true
transforms: invalid
""",
        encoding="utf-8",
    )

    config = load_alert_config(config_path)

    assert config.client.id == "fallback-demo"
    assert config.alerts.github_issues is True


def test_alert_config_fallback_uses_cli_default_when_yaml_is_unreadable(tmp_path: Path) -> None:
    config_path = tmp_path / "invalid.yaml"
    config_path.write_text("client: [", encoding="utf-8")

    config = load_alert_config(config_path, "cli-client")

    assert config.client.id == "cli-client"
