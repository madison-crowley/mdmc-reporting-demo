from __future__ import annotations

from collections.abc import Iterable
from typing import Any
import logging

from google.api_core.exceptions import NotFound
from google.cloud import bigquery
import pandas as pd


LOGGER = logging.getLogger(__name__)


def _normalize_record_value(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except TypeError:
            return value
    return value


class BigQueryWarehouse:
    def __init__(self, client: bigquery.Client) -> None:
        self.client = client

    def ensure_dataset(self, dataset_id: str) -> None:
        dataset = bigquery.Dataset(f"{self.client.project}.{dataset_id}")
        self.client.create_dataset(dataset, exists_ok=True)

    def run_sql(self, sql: str) -> None:
        LOGGER.info("Executing SQL statement.")
        self.client.query(sql).result()

    def query_dataframe(self, sql: str) -> pd.DataFrame:
        rows = [dict(row.items()) for row in self.client.query(sql).result()]
        return pd.DataFrame(rows)

    def query_scalar(self, sql: str, field_name: str) -> Any:
        rows = list(self.client.query(sql).result())
        if not rows:
            return None
        return rows[0].get(field_name)

    def load_records(self, table_fqn: str, records: Iterable[dict[str, Any]], schema: list[tuple[str, str]]) -> None:
        normalized_records = [
            {key: _normalize_record_value(value) for key, value in record.items()}
            for record in records
        ]
        job_config = bigquery.LoadJobConfig(
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
            schema=[bigquery.SchemaField(name, field_type) for name, field_type in schema],
        )
        self.client.load_table_from_json(normalized_records, table_fqn, job_config=job_config).result()

    def table_exists(self, table_fqn: str) -> bool:
        try:
            self.client.get_table(table_fqn)
            return True
        except NotFound:
            return False
