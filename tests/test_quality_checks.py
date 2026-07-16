from __future__ import annotations

from datetime import date

from mdmc_platform.quality_checks import evaluate_freshness


def test_freshness_fails_when_max_date_is_in_the_future() -> None:
    lag_days, passed = evaluate_freshness(
        max_date=date(2026, 7, 16),
        expected_date=date(2026, 7, 15),
        max_lag_days=0,
    )

    assert lag_days == -1
    assert passed is False


def test_freshness_passes_when_max_date_matches_expected_date() -> None:
    lag_days, passed = evaluate_freshness(
        max_date=date(2026, 7, 15),
        expected_date=date(2026, 7, 15),
        max_lag_days=0,
    )

    assert lag_days == 0
    assert passed is True
