from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import os

import yaml


class ConfigValidationError(ValueError):
    """Raised when the client deployment config is invalid."""


def _expect_mapping(value: Any, *, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigValidationError(f"{path} must be a mapping.")
    return value


def _expect_list(value: Any, *, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise ConfigValidationError(f"{path} must be a list.")
    return value


def _expect_string(value: Any, *, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigValidationError(f"{path} must be a non-empty string.")
    return value.strip()


def _expect_bool(value: Any, *, path: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigValidationError(f"{path} must be a boolean.")
    return value


def _expect_int(value: Any, *, path: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigValidationError(f"{path} must be an integer.")
    return value


@dataclass(frozen=True)
class ClientSettings:
    id: str
    display_name: str


@dataclass(frozen=True)
class WarehouseSettings:
    dataset_prefix: str


@dataclass(frozen=True)
class SourceConfig:
    name: str
    connector: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TransformSettings:
    date_shift: bool
    reconciliation_threshold_pct: int = 10
    rolling_window_days: int = 28


@dataclass(frozen=True)
class QualitySettings:
    checks: dict[str, dict[str, Any]] = field(default_factory=dict)
    severity_overrides: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AlertSettings:
    github_issues: bool
    slack_webhook_env: str | None = None


@dataclass(frozen=True)
class PipelineConfig:
    project_id: str
    client: ClientSettings
    warehouse: WarehouseSettings
    sources: tuple[SourceConfig, ...]
    transforms: TransformSettings
    quality: QualitySettings
    alerts: AlertSettings
    config_path: Path

    @property
    def raw_dataset(self) -> str:
        return f"{self.warehouse.dataset_prefix}_raw"

    @property
    def marts_dataset(self) -> str:
        return f"{self.warehouse.dataset_prefix}_marts"

    def table_fqn(self, dataset: str, table_name: str) -> str:
        return f"{self.project_id}.{dataset}.{table_name}"

    def raw_table_fqn(self, table_name: str) -> str:
        return self.table_fqn(self.raw_dataset, table_name)

    def mart_table_fqn(self, table_name: str) -> str:
        return self.table_fqn(self.marts_dataset, table_name)

    @classmethod
    def load(cls, path: str | Path, project_id: str | None = None) -> "PipelineConfig":
        config_path = Path(path)
        if not config_path.exists():
            raise ConfigValidationError(f"Config file not found: {config_path}")

        payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if not isinstance(payload, dict):
            raise ConfigValidationError("The config root must be a YAML mapping.")

        resolved_project_id = project_id or os.getenv("GCP_PROJECT_ID")
        if not resolved_project_id:
            raise ConfigValidationError("GCP_PROJECT_ID must be set before loading a deployment config.")

        client_block = _expect_mapping(payload.get("client"), path="client")
        warehouse_block = _expect_mapping(payload.get("warehouse"), path="warehouse")
        sources_block = _expect_list(payload.get("sources"), path="sources")
        transforms_block = _expect_mapping(payload.get("transforms", {}), path="transforms")
        quality_block = _expect_mapping(payload.get("quality", {}), path="quality")
        alerts_block = _expect_mapping(payload.get("alerts", {}), path="alerts")

        client = ClientSettings(
            id=_expect_string(client_block.get("id"), path="client.id"),
            display_name=_expect_string(client_block.get("display_name"), path="client.display_name"),
        )
        warehouse = WarehouseSettings(
            dataset_prefix=_expect_string(warehouse_block.get("dataset_prefix"), path="warehouse.dataset_prefix"),
        )

        sources: list[SourceConfig] = []
        seen_names: set[str] = set()
        for index, source_payload in enumerate(sources_block):
            path_prefix = f"sources[{index}]"
            source_block = _expect_mapping(source_payload, path=path_prefix)
            source = SourceConfig(
                name=_expect_string(source_block.get("name"), path=f"{path_prefix}.name"),
                connector=_expect_string(source_block.get("connector"), path=f"{path_prefix}.connector"),
                params=_expect_mapping(source_block.get("params", {}), path=f"{path_prefix}.params"),
            )
            if source.name in seen_names:
                raise ConfigValidationError(f"Duplicate source name found: {source.name}")
            seen_names.add(source.name)
            sources.append(source)
        if not sources:
            raise ConfigValidationError("sources must include at least one source.")

        transforms = TransformSettings(
            date_shift=_expect_bool(transforms_block.get("date_shift"), path="transforms.date_shift"),
            reconciliation_threshold_pct=_expect_int(
                transforms_block.get("reconciliation_threshold_pct", 10),
                path="transforms.reconciliation_threshold_pct",
            ),
            rolling_window_days=_expect_int(
                transforms_block.get("rolling_window_days", 28),
                path="transforms.rolling_window_days",
            ),
        )

        checks_payload = quality_block.get("checks", {})
        if checks_payload is None:
            checks_payload = {}
        checks = _expect_mapping(checks_payload, path="quality.checks")
        for check_name, check_settings in checks.items():
            _expect_mapping(check_settings, path=f"quality.checks.{check_name}")

        severity_payload = quality_block.get("severity_overrides", {})
        if severity_payload is None:
            severity_payload = {}
        severity_overrides = _expect_mapping(severity_payload, path="quality.severity_overrides")
        for check_name, severity in severity_overrides.items():
            normalized = _expect_string(severity, path=f"quality.severity_overrides.{check_name}").upper()
            if normalized not in {"CRITICAL", "WARN"}:
                raise ConfigValidationError(
                    f"quality.severity_overrides.{check_name} must be CRITICAL or WARN."
                )
            severity_overrides[check_name] = normalized

        slack_webhook_env = alerts_block.get("slack_webhook_env")
        if slack_webhook_env is not None:
            slack_webhook_env = _expect_string(slack_webhook_env, path="alerts.slack_webhook_env")
        alerts = AlertSettings(
            github_issues=_expect_bool(alerts_block.get("github_issues"), path="alerts.github_issues"),
            slack_webhook_env=slack_webhook_env,
        )

        return cls(
            project_id=resolved_project_id,
            client=client,
            warehouse=warehouse,
            sources=tuple(sources),
            transforms=transforms,
            quality=QualitySettings(checks=checks, severity_overrides=severity_overrides),
            alerts=alerts,
            config_path=config_path,
        )
