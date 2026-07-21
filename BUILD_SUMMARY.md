# Senior Review Fix Build Summary

This build implements the eight scoped senior-review fixes without beginning the
later connector-contract, deployment-plan, atomic-publishing, or OIDC refactors.

1. Reconciliation zero baselines
   - `sql/reconciliation.sql`
   - `tests/test_transform.py`
   - `tests/test_schema_contract.py`
2. Stable alert incidents and config-failure fallback
   - `mdmc_platform/alerts.py`
   - `scripts/send_alerts.py`
   - `tests/test_alerts.py`
   - `README.md`
3. Current-run expected mart enforcement
   - `mdmc_platform/quality_checks.py`
   - `scripts/run_pipeline.py`
   - `tests/test_quality_checks.py`
4. Common source watermark windows
   - `mdmc_platform/transform.py`
   - `sql/kpi_summary.sql`
   - `mdmc_platform/quality_checks.py`
   - `tests/test_transform.py`
   - `tests/test_quality_checks.py`
5. Independent BigQuery SQL dry runs
   - `scripts/lint_sql.py`
   - `mdmc_platform/connectors/ga4_bigquery_sample.py`
   - `tests/test_lint_sql.py`
6. Step-scoped workflow secrets and concurrency
   - `.github/workflows/pipeline.yml`
   - `.github/workflows/ci.yml`
   - `tests/test_workflows.py`
7. Current-window warning checks with historical metadata
   - `mdmc_platform/quality_checks.py`
   - `tests/test_quality_checks.py`
8. Presentation alignment and attribution disclosure
   - `mdmc_platform/quality_checks.py`
   - `scripts/run_pipeline.py`
   - `mdmc_platform/connectors/ga4_bigquery_sample.py`
   - `configs/demo.yaml`
   - `README.md`
   - `tests/test_quality_checks.py`
