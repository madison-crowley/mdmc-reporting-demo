from __future__ import annotations

from datetime import date
from hashlib import md5
from typing import Iterable

import pandas as pd

from mdmc_platform.connectors.base import BaseConnector, ExtractResult, ExtractedTable


AD_PLATFORM_SCHEMA = [
    ("source_date", "DATE"),
    ("date", "DATE"),
    ("platform", "STRING"),
    ("campaign_name", "STRING"),
    ("impressions", "INT64"),
    ("clicks", "INT64"),
    ("spend", "FLOAT64"),
    ("platform_reported_conversions", "INT64"),
]


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
    raw_allocations = [(total * (weight / weight_sum)) if weight_sum else 0 for weight in weights]
    floored = [int(value) for value in raw_allocations]
    remainder = total - sum(floored)
    ranked = sorted(
        enumerate(raw_allocations),
        key=lambda item: item[1] - int(item[1]),
        reverse=True,
    )
    for index, _ in ranked[:remainder]:
        floored[index] += 1
    return floored


def _build_platform_rows(
    *,
    ga4_day: pd.DataFrame,
    platform: str,
    seed: int,
    exact_campaigns: list[str],
    unmatched_campaigns: list[str],
) -> list[dict[str, object]]:
    day = pd.to_datetime(ga4_day["source_date"].iloc[0]).date()
    matched_rows = ga4_day[ga4_day["campaign"].isin(exact_campaigns)].copy()
    matched_total = int(matched_rows["purchases"].sum())
    delta_pct = _stable_ratio(seed, platform, day.isoformat(), "delta", minimum=0.03, maximum=0.14)
    direction = 1 if _stable_int(seed, platform, day.isoformat(), "direction") % 2 == 0 else -1

    # Keep platform-reported conversions within the requested 3-14% band vs matched GA4 purchases.
    target_total = max(0, int(round(matched_total * (1 + (direction * delta_pct)))))
    matched_weights = [max(int(value), 1) for value in matched_rows["purchases"].tolist()]
    allocated_conversions = _allocate_whole_numbers(target_total, matched_weights)

    rows: list[dict[str, object]] = []
    for (_, source_row), conversions in zip(matched_rows.iterrows(), allocated_conversions):
        campaign = str(source_row["campaign"])
        ctr = _stable_ratio(seed, platform, campaign, day.isoformat(), "ctr", minimum=0.02, maximum=0.065)
        cpc = _stable_ratio(seed, platform, campaign, day.isoformat(), "cpc", minimum=1.6, maximum=4.9)
        clicks = max(conversions * (3 + (_stable_int(seed, campaign, day.isoformat(), "click-multiplier") % 5)), 12)
        impressions = int(round(clicks / ctr))
        spend = round(clicks * cpc, 2)
        rows.append(
            {
                "source_date": day,
                "date": day,
                "platform": platform,
                "campaign_name": campaign,
                "impressions": impressions,
                "clicks": clicks,
                "spend": spend,
                "platform_reported_conversions": conversions,
            }
        )

    for campaign in unmatched_campaigns:
        ctr = _stable_ratio(seed, platform, campaign, day.isoformat(), "ctr", minimum=0.015, maximum=0.05)
        cpc = _stable_ratio(seed, platform, campaign, day.isoformat(), "cpc", minimum=1.2, maximum=3.8)
        clicks = 8 + (_stable_int(seed, platform, campaign, day.isoformat(), "clicks") % 20)
        impressions = int(round(clicks / ctr))
        spend = round(clicks * cpc, 2)
        rows.append(
            {
                "source_date": day,
                "date": day,
                "platform": platform,
                "campaign_name": campaign,
                "impressions": impressions,
                "clicks": clicks,
                "spend": spend,
                "platform_reported_conversions": 0,
            }
        )
    return rows


def generate_synthetic_ads(ga4_frame: pd.DataFrame, seed: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Generate deterministic demo-only ad-platform extracts from GA4 campaign demand."""

    normalized = ga4_frame.copy()
    normalized["source_date"] = pd.to_datetime(normalized["source_date"]).dt.date
    normalized["campaign"] = normalized["campaign"].astype(str)
    grouped = (
        normalized.groupby(["source_date", "campaign"], as_index=False)["purchases"]
        .sum()
        .sort_values(["source_date", "campaign"])
    )

    top_campaigns = (
        grouped.groupby("campaign", as_index=False)["purchases"]
        .sum()
        .sort_values("purchases", ascending=False)["campaign"]
        .tolist()
    )
    top_campaigns = [campaign for campaign in top_campaigns if campaign != "(not set)"][:6]
    google_exact = top_campaigns[:4]
    meta_exact = top_campaigns[2:6] if len(top_campaigns) >= 6 else top_campaigns[:4]

    google_rows: list[dict[str, object]] = []
    meta_rows: list[dict[str, object]] = []
    for _, ga4_day in grouped.groupby("source_date"):
        google_rows.extend(
            _build_platform_rows(
                ga4_day=ga4_day,
                platform="Google Ads",
                seed=seed,
                exact_campaigns=google_exact,
                unmatched_campaigns=["Search | Brand Protect", "YouTube | Local Reach"],
            )
        )
        meta_rows.extend(
            _build_platform_rows(
                ga4_day=ga4_day,
                platform="Meta Ads",
                seed=seed + 17,
                exact_campaigns=meta_exact,
                unmatched_campaigns=["Meta | Retargeting Burst", "Meta | Walk-In Awareness"],
            )
        )

    google_frame = pd.DataFrame(google_rows).sort_values(["source_date", "campaign_name"]).reset_index(drop=True)
    meta_frame = pd.DataFrame(meta_rows).sort_values(["source_date", "campaign_name"]).reset_index(drop=True)
    return google_frame, meta_frame


class SyntheticAdsConnector(BaseConnector):
    """Demo-only stand-in for live Google Ads and Meta Ads API connectors."""

    registry_key = "synthetic_ads"
    source_category = "ad_platform"

    def extract(self, warehouse, completed_extracts: list[ExtractResult]) -> ExtractResult:
        web_tables = [
            table
            for extract in completed_extracts
            if extract.source_category == "web_analytics"
            for table in extract.tables
        ]
        if not web_tables:
            raise RuntimeError("synthetic_ads requires a web_analytics extract to run first.")

        seed = int(self.source.params.get("seed", 13))
        source_sql = f"""
SELECT source_date, campaign, purchases
FROM `{web_tables[0].table_fqn}`
ORDER BY source_date, campaign
"""
        ga4_frame = warehouse.query_dataframe(source_sql)
        google_frame, meta_frame = generate_synthetic_ads(ga4_frame, seed)

        google_table_name = self.source.params.get("google_table_name", self.build_table_name("google"))
        meta_table_name = self.source.params.get("meta_table_name", self.build_table_name("meta"))
        google_table_fqn = self.config.raw_table_fqn(google_table_name)
        meta_table_fqn = self.config.raw_table_fqn(meta_table_name)

        warehouse.load_records(google_table_fqn, google_frame.to_dict(orient="records"), AD_PLATFORM_SCHEMA)
        warehouse.load_records(meta_table_fqn, meta_frame.to_dict(orient="records"), AD_PLATFORM_SCHEMA)

        return ExtractResult(
            source_name=self.source.name,
            source_category=self.source_category,
            tables=(
                ExtractedTable(self.source.name, self.source_category, google_table_name, google_table_fqn),
                ExtractedTable(self.source.name, self.source_category, meta_table_name, meta_table_fqn),
            ),
        )
