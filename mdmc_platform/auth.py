from __future__ import annotations

import json
import os

from google.cloud import bigquery
from google.oauth2 import service_account


def load_credentials_from_env(env_var: str = "GCP_SA_KEY") -> service_account.Credentials:
    raw_value = os.getenv(env_var)
    if not raw_value:
        raise RuntimeError(f"{env_var} must be set to a raw Google service-account JSON string.")
    try:
        payload = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{env_var} must contain valid JSON: {exc}") from exc
    return service_account.Credentials.from_service_account_info(payload)


def create_bigquery_client(project_id: str, credentials: service_account.Credentials | None = None) -> bigquery.Client:
    resolved_credentials = credentials or load_credentials_from_env()
    return bigquery.Client(project=project_id, credentials=resolved_credentials)
