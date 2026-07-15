from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import re

from mdmc_platform.config import PipelineConfig, SourceConfig


SOURCE_CATEGORIES = {"web_analytics", "ad_platform", "booking_system"}


def slugify_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


@dataclass(frozen=True)
class ExtractedTable:
    source_name: str
    source_category: str
    table_name: str
    table_fqn: str


@dataclass(frozen=True)
class ExtractResult:
    source_name: str
    source_category: str
    tables: tuple[ExtractedTable, ...]


class BaseConnector(ABC):
    registry_key = ""
    source_category = ""

    def __init__(self, source: SourceConfig, config: PipelineConfig) -> None:
        self.source = source
        self.config = config
        if self.source_category not in SOURCE_CATEGORIES:
            raise ValueError(f"Unsupported source category: {self.source_category}")

    def build_table_name(self, suffix: str | None = None) -> str:
        base = slugify_name(self.source.name)
        if suffix:
            return f"{base}_{suffix}"
        return base

    def build_table_fqn(self, suffix: str | None = None) -> str:
        return self.config.raw_table_fqn(self.build_table_name(suffix))

    @abstractmethod
    def extract(self, warehouse, completed_extracts: list[ExtractResult]) -> ExtractResult:
        """Materialize raw tables and return the tables created for this source."""
