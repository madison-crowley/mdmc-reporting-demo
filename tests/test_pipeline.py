from __future__ import annotations

from mdmc_platform.connectors.base import ExtractedTable, ExtractResult
from scripts.run_pipeline import build_extraction_metadata


def test_extraction_metadata_records_rows_and_current_run_timestamp() -> None:
    class _Warehouse:
        def query_scalar(self, sql: str, field_name: str) -> int:
            assert field_name == "row_count"
            return 12 if "table_a" in sql else 8

    extract = ExtractResult(
        source_name="paid-media",
        source_category="ad_platform",
        tables=(
            ExtractedTable("paid-media", "ad_platform", "table_a", "demo.raw.table_a"),
            ExtractedTable("paid-media", "ad_platform", "table_b", "demo.raw.table_b"),
        ),
    )

    metadata = build_extraction_metadata(_Warehouse(), extract)

    assert metadata["source_name"] == "paid-media"
    assert metadata["source_category"] == "ad_platform"
    assert metadata["rows_loaded"] == 20
    assert metadata["extracted_at"].endswith("Z")
    assert [table["rows_loaded"] for table in metadata["tables"]] == [12, 8]
