from __future__ import annotations

from mdmc_platform.connectors.base import BaseConnector
from mdmc_platform.connectors.ga4_bigquery_sample import Ga4BigQuerySampleConnector
from mdmc_platform.connectors.synthetic_ads import SyntheticAdsConnector
from mdmc_platform.connectors.synthetic_bookings import SyntheticBookingsConnector
from mdmc_platform.config import PipelineConfig, SourceConfig


CONNECTOR_REGISTRY: dict[str, type[BaseConnector]] = {
    Ga4BigQuerySampleConnector.registry_key: Ga4BigQuerySampleConnector,
    SyntheticAdsConnector.registry_key: SyntheticAdsConnector,
    SyntheticBookingsConnector.registry_key: SyntheticBookingsConnector,
}


def build_connector(source: SourceConfig, config: PipelineConfig) -> BaseConnector:
    try:
        connector_class = CONNECTOR_REGISTRY[source.connector]
    except KeyError as exc:
        available = ", ".join(sorted(CONNECTOR_REGISTRY))
        raise KeyError(f"Unknown connector '{source.connector}'. Available connectors: {available}") from exc
    return connector_class(source, config)
