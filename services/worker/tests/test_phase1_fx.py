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
    StaleBaseCurrencyRefreshError,
    stamp_fx,
)
from worker.models import CanonicalTransaction, Direction, ParsedTransaction
from worker.repository import InMemoryRepository


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


@pytest.mark.parametrize("rate_date", [date(2025, 12, 25), date(2026, 1, 4)])
def test_stamping_rejects_stale_or_future_quotes_from_any_provider(rate_date: date) -> None:
    class UnsafeProvider:
        def get_rate(self, *, base: str, quote: str, as_of: date) -> RateQuote:
            return RateQuote(Decimal("1.25"), rate_date, "unsafe-test")

    transaction = ParsedTransaction(
        booked_date=date(2026, 1, 3),
        description_raw="Synthetic purchase",
        amount_native=Decimal("10.00"),
        currency_native="USD",
        direction=Direction.DEBIT,
    )

    with pytest.raises(MissingFXRateError):
        stamp_fx(transaction, provider=UnsafeProvider())


def test_canonical_reporting_layer_accepts_fractional_cent_rounding() -> None:
    class TzsProvider:
        def get_rate(self, *, base: str, quote: str, as_of: date) -> RateQuote:
            assert (base, quote) == ("TZS", "CAD")
            return RateQuote(Decimal("0.00054"), as_of, "rounding-test")

    parsed = ParsedTransaction(
        booked_date=date(2026, 1, 20),
        description_raw="Synthetic TZS deposit",
        amount_native=Decimal("529973.00"),
        currency_native="TZS",
        direction=Direction.CREDIT,
    )
    stamped = stamp_fx(parsed, provider=TzsProvider())
    transaction = CanonicalTransaction(
        **parsed.model_dump(exclude={"enrichment"}),
        amount_base=stamped.amount_base,
        currency_base=stamped.currency_base,
        fx_rate=stamped.rate,
        fx_rate_date=stamped.rate_date,
        merchant_name="Synthetic TZS deposit",
        merchant_key="synthetic tzs deposit",
        category_name="Income",
        category_kind="income",
        dedup_hash="fractional-cent-rounding",
    )

    assert transaction.amount_base == Decimal("286.19")


def test_worker_rejects_invalid_inline_and_standalone_fee_shapes() -> None:
    with pytest.raises(ValueError, match="cannot exceed"):
        ParsedTransaction(
            booked_date=date(2026, 1, 3),
            description_raw="Synthetic purchase",
            amount_native=Decimal("10.00"),
            fx_fee_amount_native=Decimal("11.00"),
            direction=Direction.DEBIT,
        )
    with pytest.raises(ValueError, match="fee direction"):
        ParsedTransaction(
            booked_date=date(2026, 1, 3),
            description_raw="Synthetic FX charge",
            amount_native=Decimal("10.00"),
            is_fx_fee=True,
            direction=Direction.DEBIT,
        )


class _RebuildRepository:
    def __init__(self) -> None:
        self.base_currency = "CAD"
        self.rebuilt: tuple[str, int, bool] | None = None
        self.analytics_refreshes: list[str] = []
        self.fx_refreshes: list[str] = []

    def get_base_currency(self) -> str:
        return self.base_currency

    def list_fx_requirements(self, *, target_currency: str) -> tuple[FXRequirement, ...]:
        return (
            FXRequirement("USD", target_currency, date(2026, 1, 2)),
            FXRequirement("TZS", target_currency, date(2026, 1, 2)),
        )

    def rebuild_base_currency(
        self,
        *,
        target_currency: str,
        max_staleness_days: int,
        allow_currency_change: bool = False,
    ) -> int:
        if target_currency != self.base_currency and not allow_currency_change:
            raise StaleBaseCurrencyRefreshError(
                requested=target_currency,
                active=self.base_currency,
            )
        self.rebuilt = (target_currency, max_staleness_days, allow_currency_change)
        self.base_currency = target_currency
        return 12

    def enqueue_analytics_refresh_job(self, *, mode: str = "incremental") -> None:
        self.analytics_refreshes.append(mode)

    def enqueue_fx_refresh_job(self, *, target_base_currency: str) -> None:
        self.fx_refreshes.append(target_base_currency)


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
    ).run({"target_base_currency": "CAD"})

    assert refreshed == {
        "base_currency": "CAD",
        "quote_currencies": ["TZS", "USD"],
        "rates_stored": 2,
        "transactions_updated": 12,
    }
    assert rebuilt == {
        "previous_base_currency": "CAD",
        "target_base_currency": "CAD",
        "transactions_updated": 12,
        "settings_updated": True,
    }
    assert repository.rebuilt == ("CAD", 7, True)
    assert repository.analytics_refreshes == ["incremental", "full"]

    with pytest.raises(ValueError, match="CAD or TZS"):
        BaseCurrencyRebuildService(
            repository=repository,
            provider=provider,
            max_staleness_days=7,
        ).run({"target_base_currency": "USD"})


def test_base_switch_succeeds_with_pending_history_and_queues_recovery() -> None:
    class PartiallyUnavailableProvider(FixtureFXRateProvider):
        def get_rate(self, *, base: str, quote: str, as_of: date) -> RateQuote:
            if base == "USD":
                raise MissingFXRateError("historical USD rate unavailable")
            return super().get_rate(base=base, quote=quote, as_of=as_of)

    repository = _RebuildRepository()

    result = BaseCurrencyRebuildService(
        repository=repository,
        provider=PartiallyUnavailableProvider(),
    ).run({"target_base_currency": "CAD"})

    assert result == {
        "previous_base_currency": "CAD",
        "target_base_currency": "CAD",
        "transactions_updated": 12,
        "settings_updated": True,
        "pending_rate_count": 1,
    }
    assert repository.analytics_refreshes == ["full"]
    assert repository.fx_refreshes == ["CAD"]


def test_stale_fx_refresh_cannot_revert_a_completed_currency_switch() -> None:
    repository = _RebuildRepository()
    provider = FixtureFXRateProvider()
    switch = BaseCurrencyRebuildService(repository=repository, provider=provider)
    refresh = FXRefreshService(repository=repository, provider=provider)

    switched = switch.run({"target_base_currency": "TZS"})
    stale = refresh.run({"target_base_currency": "CAD"})

    assert switched["target_base_currency"] == "TZS"
    assert repository.base_currency == "TZS"
    assert repository.rebuilt == ("TZS", 7, True)
    assert stale == {
        "base_currency": "TZS",
        "requested_base_currency": "CAD",
        "stale": True,
        "quote_currencies": [],
        "rates_stored": 0,
        "transactions_updated": 0,
    }
    assert repository.analytics_refreshes == ["full"]

    with pytest.raises(StaleBaseCurrencyRefreshError):
        repository.rebuild_base_currency(
            target_currency="CAD",
            max_staleness_days=7,
        )


def test_currency_switch_rescans_fx_after_the_prelock_requirement_snapshot() -> None:
    class InterleavingRepository(_RebuildRepository):
        def __init__(self) -> None:
            super().__init__()
            self.snapshot_complete = False
            self.pending_row_added = False
            self.followups: list[str] = []

        def list_fx_requirements(
            self,
            *,
            target_currency: str,
        ) -> tuple[FXRequirement, ...]:
            self.snapshot_complete = True
            return ()

        def rebuild_base_currency(
            self,
            *,
            target_currency: str,
            max_staleness_days: int,
            allow_currency_change: bool = False,
        ) -> int:
            assert self.snapshot_complete
            # Simulate ingestion committing a native-currency transaction after
            # list_fx_requirements but before the switch acquires its DB lock.
            self.pending_row_added = True
            return super().rebuild_base_currency(
                target_currency=target_currency,
                max_staleness_days=max_staleness_days,
                allow_currency_change=allow_currency_change,
            )

        def enqueue_fx_refresh_job(self, *, target_base_currency: str) -> None:
            self.followups.append(f"fx:{target_base_currency}")
            super().enqueue_fx_refresh_job(
                target_base_currency=target_base_currency,
            )

        def enqueue_analytics_refresh_job(self, *, mode: str = "incremental") -> None:
            self.followups.append(f"analytics:{mode}")
            super().enqueue_analytics_refresh_job(mode=mode)

    repository = InterleavingRepository()

    result = BaseCurrencyRebuildService(
        repository=repository,
        provider=FixtureFXRateProvider(),
    ).run({"target_base_currency": "TZS"})

    assert repository.pending_row_added
    assert result["target_base_currency"] == "TZS"
    assert "pending_rate_count" not in result
    assert repository.fx_refreshes == ["TZS"]
    assert repository.followups == ["fx:TZS", "analytics:full"]


def test_tzs_is_a_supported_reporting_currency() -> None:
    parsed = ParsedTransaction(
        booked_date=date(2026, 1, 20),
        description_raw="Synthetic TZS deposit",
        amount_native=Decimal("529973.00"),
        currency_native="TZS",
        direction=Direction.CREDIT,
    )

    stamped = stamp_fx(parsed, base_currency="TZS")
    transaction = CanonicalTransaction(
        **parsed.model_dump(),
        amount_base=stamped.amount_base,
        currency_base=stamped.currency_base,
        fx_rate=stamped.rate,
        fx_rate_date=stamped.rate_date,
        merchant_name="Synthetic TZS deposit",
        merchant_key="synthetic tzs deposit",
        category_name="Income",
        category_kind="income",
        dedup_hash="tzs-identity",
    )

    assert transaction.amount_base == Decimal("529973.00")
    assert transaction.currency_base == "TZS"
    assert transaction.fx_rate == Decimal("1")


def test_base_rebuild_never_reuses_a_previous_reporting_value() -> None:
    parsed = ParsedTransaction(
        booked_date=date(2026, 1, 20),
        description_raw="Synthetic USD purchase",
        amount_native=Decimal("10.00"),
        currency_native="USD",
        direction=Direction.DEBIT,
    )
    transaction = CanonicalTransaction(
        **parsed.model_dump(exclude={"enrichment"}),
        amount_base=Decimal("14.00"),
        currency_base="CAD",
        fx_rate=Decimal("1.4"),
        fx_rate_date=parsed.booked_date,
        merchant_name="Synthetic USD purchase",
        merchant_key="synthetic usd purchase",
        category_name="Other",
        category_kind="expense",
        dedup_hash="unsafe-old-base",
        enrichment={"fx_source": "old-rate"},
    )
    repository = InMemoryRepository(base_currency="CAD")
    repository.transactions[transaction.dedup_hash] = transaction

    repository.rebuild_base_currency(
        target_currency="TZS",
        max_staleness_days=7,
        allow_currency_change=True,
    )

    rebuilt = repository.transactions[transaction.dedup_hash]
    assert rebuilt.currency_base == "TZS"
    assert rebuilt.amount_base is None
    assert rebuilt.fx_rate is None
    assert rebuilt.fx_rate_date is None
    assert "fx_source" not in rebuilt.enrichment
