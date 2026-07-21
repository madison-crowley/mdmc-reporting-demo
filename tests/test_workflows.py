from __future__ import annotations

from pathlib import Path


def test_pipeline_workflow_scopes_secrets_to_steps_and_serializes_runs() -> None:
    workflow = Path(".github/workflows/pipeline.yml").read_text(encoding="utf-8")
    job_header = workflow.split("steps:", 1)[0]

    assert "secrets.GCP_PROJECT_ID" not in job_header
    assert "secrets.GCP_SA_KEY" not in job_header
    assert "secrets.SLACK_WEBHOOK_URL" not in job_header
    assert "secrets.PIPELINE_ALERT_WEBHOOK" not in job_header
    assert "group: pipeline-${{" in workflow
    assert "cancel-in-progress: false" in workflow
    assert workflow.count("secrets.GCP_PROJECT_ID") == 1
    assert workflow.count("secrets.GCP_SA_KEY") == 1


def test_ci_workflow_keeps_cloud_secrets_out_of_pytest_job_scope() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    job_header = workflow.split("steps:", 1)[0]
    pytest_step = workflow.split("- name: Run pytest", 1)[1].split("- name: Dry-run lint rendered SQL", 1)[0]

    assert "secrets.GCP_PROJECT_ID" not in job_header
    assert "secrets.GCP_SA_KEY" not in job_header
    assert "secrets.GCP_PROJECT_ID" not in pytest_step
    assert "secrets.GCP_SA_KEY" not in pytest_step
    assert workflow.count("secrets.GCP_PROJECT_ID") == 1
    assert workflow.count("secrets.GCP_SA_KEY") == 1
