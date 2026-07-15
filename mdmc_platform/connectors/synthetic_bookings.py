from __future__ import annotations

from hashlib import md5

import pandas as pd

from mdmc_platform.connectors.base import BaseConnector, ExtractResult, ExtractedTable


BOOKING_SYSTEM_SCHEMA = [
    ("source_date", "DATE"),
    ("date", "DATE"),
    ("booking_date", "DATE"),
    ("service_category", "STRING"),
    ("appointments_booked", "INT64"),
    ("appointments_completed", "INT64"),
    ("no_shows", "INT64"),
    ("booking_revenue", "FLOAT64"),
    ("acquisition_channel", "STRING"),
]

SERVICE_PRICES = {
    "facial": 165.0,
    "massage": 140.0,
    "injectables": 325.0,
    "membership": 99.0,
}


def _stable_int(*parts: object) -> int:
    payload = "||".join(str(part) for part in parts)
    return int(md5(payload.encode("utf-8")).hexdigest()[:12], 16)


def _stable_ratio(*parts: object, minimum: float = 0.0, maximum: float = 1.0) -> float:
    span = maximum - minimum
    return minimum + ((_stable_int(*parts) % 10_000) / 10_000.0) * span


def _allocate_whole_numbers(total: int, weights: list[float]) -> list[int]:
    if total <= 0 or not weights:
        return [0 for _ in weights]
    weight_sum = sum(weights)
    base = [int(total * (weight / weight_sum)) if weight_sum else 0 for weight in weights]
    remainder = total - sum(base)
    ranked = sorted(enumerate(weights), key=lambda item: item[1], reverse=True)
    for index, _ in ranked[:remainder]:
        base[index] += 1
    return base


def generate_synthetic_bookings(web_analytics_frame: pd.DataFrame, seed: int) -> pd.DataFrame:
    """Generate deterministic demo-only booking data with attribution leakage."""

    normalized = web_analytics_frame.copy()
    normalized["source_date"] = pd.to_datetime(normalized["source_date"]).dt.date
    normalized["channel"] = normalized["source"].astype(str) + " / " + normalized["medium"].astype(str)
    channel_sessions = (
        normalized.groupby(["source_date", "channel"], as_index=False)["sessions"]
        .sum()
        .sort_values(["source_date", "channel"])
    )

    rows: list[dict[str, object]] = []
    service_categories = list(SERVICE_PRICES.keys())

    for source_date, day_frame in channel_sessions.groupby("source_date"):
        day = pd.Timestamp(source_date).date()
        total_sessions = int(day_frame["sessions"].sum())
        total_booked = max(4, int(round(total_sessions * _stable_ratio(seed, day, "booked", minimum=0.026, maximum=0.038))))

        unknown_share = _stable_ratio(seed, day, "unknown", minimum=0.12, maximum=0.2)
        known_bookings = max(0, total_booked - int(round(total_booked * unknown_share)))

        channels = day_frame["channel"].tolist()
        weights = day_frame["sessions"].astype(float).tolist()
        allocations = _allocate_whole_numbers(known_bookings, weights)
        channel_allocations = list(zip(channels, allocations))
        channel_allocations.append(("unknown/walk-in", total_booked - sum(allocations)))

        for channel, channel_bookings in channel_allocations:
            if channel_bookings <= 0:
                continue
            category_weights = [
                _stable_ratio(seed, day, channel, category, minimum=0.1, maximum=1.0)
                for category in service_categories
            ]
            category_allocations = _allocate_whole_numbers(channel_bookings, category_weights)
            for category, booked in zip(service_categories, category_allocations):
                if booked <= 0:
                    continue
                no_show_rate = _stable_ratio(seed, day, channel, category, "no-show", minimum=0.05, maximum=0.16)
                no_shows = min(booked, int(round(booked * no_show_rate)))
                completed = max(0, booked - no_shows)
                revenue_multiplier = _stable_ratio(seed, day, channel, category, "revenue", minimum=0.92, maximum=1.08)
                revenue = round(completed * SERVICE_PRICES[category] * revenue_multiplier, 2)
                rows.append(
                    {
                        "source_date": day,
                        "date": day,
                        "booking_date": day,
                        "service_category": category,
                        "appointments_booked": booked,
                        "appointments_completed": completed,
                        "no_shows": no_shows,
                        "booking_revenue": revenue,
                        "acquisition_channel": channel,
                    }
                )

    return pd.DataFrame(rows).sort_values(["source_date", "acquisition_channel", "service_category"]).reset_index(drop=True)


class SyntheticBookingsConnector(BaseConnector):
    """Demo-only stand-in for live Square or Mindbody booking-system connectors."""

    registry_key = "synthetic_bookings"
    source_category = "booking_system"

    def extract(self, warehouse, completed_extracts: list[ExtractResult]) -> ExtractResult:
        web_tables = [
            table
            for extract in completed_extracts
            if extract.source_category == "web_analytics"
            for table in extract.tables
        ]
        if not web_tables:
            raise RuntimeError("synthetic_bookings requires a web_analytics extract to run first.")

        seed = int(self.source.params.get("seed", 23))
        source_sql = f"""
SELECT source_date, source, medium, sessions
FROM `{web_tables[0].table_fqn}`
ORDER BY source_date, source, medium
"""
        web_analytics_frame = warehouse.query_dataframe(source_sql)
        bookings_frame = generate_synthetic_bookings(web_analytics_frame, seed)

        table_name = self.source.params.get("table_name", self.build_table_name())
        table_fqn = self.config.raw_table_fqn(table_name)
        warehouse.load_records(table_fqn, bookings_frame.to_dict(orient="records"), BOOKING_SYSTEM_SCHEMA)

        return ExtractResult(
            source_name=self.source.name,
            source_category=self.source_category,
            tables=(
                ExtractedTable(self.source.name, self.source_category, table_name, table_fqn),
            ),
        )
