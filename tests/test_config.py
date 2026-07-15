from __future__ import annotations

from pathlib import Path

import pytest

from mdmc_platform.config import ConfigValidationError, PipelineConfig


def _write_config(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_config_loads_with_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GCP_PROJECT_ID", "demo-project")
    config_path = _write_config(
        tmp_path / "demo.yaml",
        """
client:
  id: demo
  display_name: Demo Client
warehouse:
  dataset_prefix: demo
sources:
  - name: ga4
    connector: ga4_bigquery_sample
    params: {}
transforms:
  date_shift: true
quality:
  checks: {}
alerts:
  github_issues: false
""",
    )

    config = PipelineConfig.load(config_path)

    assert config.project_id == "demo-project"
    assert config.transforms.reconciliation_threshold_pct == 10
    assert config.transforms.rolling_window_days == 28
    assert config.raw_dataset == "demo_raw"
    assert config.marts_dataset == "demo_marts"


def test_config_rejects_missing_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GCP_PROJECT_ID", "demo-project")
    config_path = _write_config(
        tmp_path / "invalid.yaml",
        """
client:
  id: demo
  display_name: Demo Client
warehouse:
  dataset_prefix: demo
sources: []
transforms:
  date_shift: true
alerts:
  github_issues: false
""",
    )

    with pytest.raises(ConfigValidationError, match="sources must include at least one source"):
        PipelineConfig.load(config_path)


def test_config_rejects_duplicate_source_names(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GCP_PROJECT_ID", "demo-project")
    config_path = _write_config(
        tmp_path / "invalid.yaml",
        """
client:
  id: demo
  display_name: Demo Client
warehouse:
  dataset_prefix: demo
sources:
  - name: duplicate
    connector: ga4_bigquery_sample
    params: {}
  - name: duplicate
    connector: synthetic_ads
    params: {}
transforms:
  date_shift: true
alerts:
  github_issues: false
""",
    )

    with pytest.raises(ConfigValidationError, match="Duplicate source name found"):
        PipelineConfig.load(config_path)
