from __future__ import annotations

from mdmc_platform.alerts import build_issue_title, build_markdown_summary, summarize_alerts


def test_summarize_alerts_marks_warn_and_critical_failures_as_alertable() -> None:
    report = {
        "generated_at": "2026-07-16T07:00:00Z",
        "checks": [
            {"check": "freshness", "severity": "CRITICAL", "value": "2026-07-14", "threshold": "2026-07-15", "passed": False},
            {"check": "reconciliation_flag_count", "severity": "WARN", "value": 12, "threshold": 0, "passed": False},
        ],
    }

    decision = summarize_alerts(report, "failure")

    assert decision.should_alert is True
    assert decision.is_clean is False
    assert {item.check for item in decision.items} >= {"freshness", "reconciliation_flag_count"}


def test_summarize_alerts_injects_pipeline_execution_failure_when_report_has_no_failed_checks() -> None:
    decision = summarize_alerts({"generated_at": "2026-07-16T07:00:00Z", "checks": []}, "failure")

    assert decision.should_alert is True
    assert decision.items[0].check == "pipeline_execution"
    assert decision.items[0].severity == "CRITICAL"


def test_build_markdown_summary_and_title_are_client_specific() -> None:
    report = {
        "generated_at": "2026-07-16T07:00:00Z",
        "checks": [
            {"check": "freshness", "severity": "CRITICAL", "value": "late", "threshold": "today", "passed": False},
        ],
    }
    decision = summarize_alerts(report, "failure")

    title = build_issue_title("demo", decision.report_date)
    body = build_markdown_summary("demo", "failure", decision.items)

    assert title == "Pipeline alert — demo — 2026-07-16"
    assert "# Pipeline alert for `demo`" in body
    assert "| `freshness` | `CRITICAL` | `late` | `today` |" in body
