from __future__ import annotations

from datetime import date

import pandas as pd

from mdmc_platform.connectors import CONNECTOR_REGISTRY
from mdmc_platform.connectors.synthetic_ads import AD_PLATFORM_SCHEMA, generate_synthetic_ads
from mdmc_platform.connectors.synthetic_bookings import generate_synthetic_bookings


def build_ga4_fixture() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"source_date": date(2021, 1, 1), "campaign": "Holiday Search", "purchases": 18, "source": "google", "medium": "cpc", "sessions": 120},
            {"source_date": date(2021, 1, 1), "campaign": "Injectables Promo", "purchases": 12, "source": "facebook", "medium": "paid_social", "sessions": 96},
            {"source_date": date(2021, 1, 1), "campaign": "Membership Push", "purchases": 9, "source": "instagram", "medium": "paid_social", "sessions": 76},
            {"source_date": date(2021, 1, 2), "campaign": "Holiday Search", "purchases": 16, "source": "google", "medium": "cpc", "sessions": 112},
            {"source_date": date(2021, 1, 2), "campaign": "Injectables Promo", "purchases": 14, "source": "facebook", "medium": "paid_social", "sessions": 102},
            {"source_date": date(2021, 1, 2), "campaign": "Membership Push", "purchases": 8, "source": "instagram", "medium": "paid_social", "sessions": 70},
            {"source_date": date(2021, 1, 2), "campaign": "Facial Refresh", "purchases": 11, "source": "google", "medium": "cpc", "sessions": 94},
        ]
    )


def test_connector_registry_contains_demo_connectors() -> None:
    assert {"ga4_bigquery_sample", "synthetic_ads", "synthetic_bookings"} <= set(CONNECTOR_REGISTRY)


def test_synthetic_ads_are_deterministic_and_calibrated() -> None:
    ga4_frame = build_ga4_fixture()[["source_date", "campaign", "purchases"]]
    first_google, first_meta = generate_synthetic_ads(ga4_frame, seed=11)
    second_google, second_meta = generate_synthetic_ads(ga4_frame, seed=11)

    pd.testing.assert_frame_equal(first_google, second_google)
    pd.testing.assert_frame_equal(first_meta, second_meta)

    for platform_frame in (first_google, first_meta):
        assert platform_frame.columns.tolist() == [name for name, _ in AD_PLATFORM_SCHEMA]
        matched_rows = platform_frame[platform_frame["matched_ga4_campaign"].notna()]
        merged = matched_rows.merge(
            ga4_frame,
            left_on=["source_date", "matched_ga4_campaign"],
            right_on=["source_date", "campaign"],
            how="left",
        )
        day_summary = (
            merged.groupby("source_date", as_index=False)
            .agg({"platform_reported_conversions": "sum", "purchases": "sum"})
        )
        discrepancy_pct = ((day_summary["platform_reported_conversions"] - day_summary["purchases"]).abs() / day_summary["purchases"]) * 100
        assert discrepancy_pct.between(3.0, 14.0).all()


def test_synthetic_ads_use_paid_display_names_and_preserve_ga4_scoping_keys() -> None:
    bucket_campaigns = ["(organic)", "(direct)", "(referral)", "(data deleted)", "(not set)", "(other)"]
    ga4_frame = pd.DataFrame(
        [
            {"source_date": date(2021, 1, 1), "campaign": campaign, "purchases": purchases}
            for campaign, purchases in zip(bucket_campaigns, range(60, 0, -10))
        ]
    )

    google_frame, meta_frame = generate_synthetic_ads(ga4_frame, seed=11)

    for platform_frame in (google_frame, meta_frame):
        matched_rows = platform_frame[platform_frame["matched_ga4_campaign"].notna()]
        unmatched_rows = platform_frame[platform_frame["matched_ga4_campaign"].isna()]
        assert set(matched_rows["matched_ga4_campaign"]) <= set(bucket_campaigns)
        assert not set(matched_rows["campaign_name"]) & set(bucket_campaigns)
        assert (matched_rows["campaign_name"] != matched_rows["matched_ga4_campaign"]).all()
        assert not unmatched_rows.empty


def test_synthetic_bookings_are_deterministic_and_include_walk_ins() -> None:
    ga4_frame = build_ga4_fixture()[["source_date", "source", "medium", "sessions"]]
    first_frame = generate_synthetic_bookings(ga4_frame, seed=29)
    second_frame = generate_synthetic_bookings(ga4_frame, seed=29)

    pd.testing.assert_frame_equal(first_frame, second_frame)
    assert "unknown/walk-in" in set(first_frame["acquisition_channel"])
    assert (first_frame["appointments_completed"] <= first_frame["appointments_booked"]).all()
