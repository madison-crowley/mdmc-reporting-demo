# Development Guide

This guide covers the technical setup and operating details for contributors working on the MDMC managed reporting demo.

## Architecture

The platform is configuration-driven:

- configuration defines each deployment
- connectors standardize source extracts
- raw datasets land in BigQuery
- SQL builds reporting marts
- Python handles execution, validation, and orchestration
- quality checks monitor presentation alignment, source watermarks, anomalies, and reconciliation drift
- alerts surface problems found during scheduled runs

The public demo deployment is defined in `configs/demo.yaml`.

## How the Pipeline Runs

The main entry point is `scripts/run_pipeline.py`.

A full run does the following:

1. Load the selected deployment configuration.
2. Run configured connectors into `<dataset_prefix>_raw`.
3. Build marts in `<dataset_prefix>_marts`.
4. Execute quality checks.
5. Write `artifacts/quality_report.json`.
6. Let GitHub Actions upload the report and dispatch alerts.

## Local Setup

Required environment variables:

- `GCP_PROJECT_ID`
- `GCP_SA_KEY` as raw service-account JSON

Create a virtual environment and install the dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Local Commands

Run the full pipeline:

```powershell
.\.venv\Scripts\python.exe scripts\run_pipeline.py --config configs/demo.yaml --step all
```

Run individual stages:

```powershell
.\.venv\Scripts\python.exe scripts\run_pipeline.py --config configs/demo.yaml --step extract
.\.venv\Scripts\python.exe scripts\run_pipeline.py --config configs/demo.yaml --step transform
.\.venv\Scripts\python.exe scripts\run_pipeline.py --config configs/demo.yaml --step checks
```

Dry-run lint the rendered BigQuery SQL:

```powershell
.\.venv\Scripts\python.exe scripts\lint_sql.py --config configs/demo.yaml
```

## Nightly Orchestration

The reusable deployment workflow is `.github/workflows/pipeline.yml`.

It runs nightly at `07:00 UTC` and can also be started manually through `workflow_dispatch`. The workflow accepts a configuration path and defaults to `configs/demo.yaml`.

Each run:

- checks out the repository
- sets up Python 3.11 with a pip cache
- installs dependencies
- runs `scripts/run_pipeline.py --config <input> --step all`
- uploads `artifacts/quality_report.json`
- dispatches GitHub and Slack alerts from the configuration’s `alerts` block

## Alerting

Alerting is controlled by the `alerts` block in each deployment configuration.

- A pipeline failure or failed `CRITICAL` or `WARN` check creates or updates a GitHub issue labeled `pipeline-alert`.
- If `alerts.slack_webhook_env` names an available environment variable, the pipeline sends a compact Slack summary.
- A fully clean run closes open `pipeline-alert` issues for that client with a resolution comment.

The public demo keeps GitHub issue alerting enabled. Its visible `pipeline-alert` issues demonstrate how one incident per client is updated across runs and resolved after a clean run. Slack is unset by default.

## Adding a Deployment

1. Add a YAML configuration.
2. Point the workflow’s `config_path` input to the new file.
3. Expose the required GCP and alerting secrets or environment variables.
4. Add and register a connector if the deployment introduces a new source type.

In the normal case, a new deployment should require new configuration and connector selection rather than changes to the platform core.

## Continuous Integration

Pull requests run `.github/workflows/ci.yml`, which:

- runs `pytest`
- performs a BigQuery dry-run lint pass against the rendered SQL

This provides feedback on Python behavior and warehouse-query validity before deployment changes are merged.
