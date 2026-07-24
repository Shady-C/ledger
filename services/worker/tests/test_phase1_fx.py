from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest

from worker.fx import (
    BaseCurrencyRebuildService,
    CachedFXRateProvider,
    FixtureFXRateProvider,
    FrankfurterFXRateProvider,
    FXRefreshService,
    FXRequirement,
    MemoryFXRateCache,
    MissingFXRateError,
    RateQuote,
)


def test_frankfurter_v2_uses_single_pair_historical_endpoint() -> None:
    seen: list[tuple[str, float]] = []

    def transport(url: str, timeout: float) -> bytes:
        seen.append((url, timeout))
        return json.dumps(
            {"date": "2026-01-02", "base": "USD", "quote": "CAD", "rate": 1.4}
        ).encode()

    provider = FrankfurterFXRateProvider(
        base_url="https://rates.example/v2",
        transport=transport,
        max_staleness_days=7,
    )

    quote = provider.get_rate(base="usd", quote="cad", as_of=date(2026, 1, 3))

    assert seen == [("https://rates.example/v2/rate/USD/CAD?date=2026-01-03", 10)]
    assert quote == RateQuote(Decimal("1.4"), date(2026, 1, 2), "frankfurter-v2")


@pytest.mark.parametrize("rate_date", ["2025-12-25", "2026-01-04"])
def test_frankfurter_rejects_stale_or_future_rates(rate_date: str) -> None:
    provider = FrankfurterFXRateProvider(
        transport=lambda _url, _timeout: json.dumps(
            {"date": rate_date, "base": "USD", "quote": "CAD", "rate": 1.4}
        ).encode(),
        max_staleness_days=7,
    )

    with pytest.raises(MissingFXRateError):
        provider.get_rate(base="USD", quote="CAD", as_of=date(2026, 1, 3))


class _CountingProvider:
    def __init__(self) -> None:
        self.calls = 0

    def get_rate(self, *, base: str, quote: str, as_of: date) -> RateQuote:
        self.calls += 1
        return RateQuote(Decimal("1.25"), as_of, "upstream")


def test_read_through_cache_reuses_actual_rate_date() -> None:
    upstream = _CountingProvider()
    cache = MemoryFXRateCache()
    provider = CachedFXRateProvider(cache=cache, upstream=upstream)

    first = provider.get_rate(base="USD", quote="CAD", as_of=date(2026, 1, 2))
    second = provider.get_rate(base="USD", quote="CAD", as_of=date(2026, 1, 3))

    assert first == second
    assert upstream.calls == 1


class _RebuildRepository:
    def __init__(self) -> None:
        self.base_currency = "CAD"
        self.rebuilt: tuple[str, int] | None = None

    def get_base_currency(self) -> str:
        return self.base_currency

    def list_fx_requirements(self, *, target_currency: str) -> tuple[FXRequirement, ...]:
        return (
            FXRequirement("USD", target_currency, date(2026, 1, 2)),
            FXRequirement("TZS", target_currency, date(2026, 1, 2)),
        )

    def rebuild_base_currency(self, *, target_currency: str, max_staleness_days: int) -> int:
        self.rebuilt = (target_currency, max_staleness_days)
        self.base_currency = target_currency
        return 12


def test_fx_jobs_have_stable_api_result_shapes_and_fixture_rates() -> None:
    repository = _RebuildRepository()
    provider = FixtureFXRateProvider()

    refreshed = FXRefreshService(repository=repository, provider=provider).run(
        {"target_base_currency": "CAD"}
    )
    rebuilt = BaseCurrencyRebuildService(
        repository=repository,
        provider=provider,
        max_staleness_days=7,
    ).run({"target_base_currency": "USD"})

    assert refreshed == {
        "base_currency": "CAD",
        "quote_currencies": ["TZS", "USD"],
        "rates_stored": 2,
    }
    assert rebuilt == {
        "previous_base_currency": "CAD",
        "target_base_currency": "USD",
        "transactions_updated": 12,
        "settings_updated": True,
    }
    assert repository.rebuilt == ("USD", 7)
