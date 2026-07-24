"""Deterministic base-currency stamping."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Protocol

from worker.models import ParsedTransaction


@dataclass(frozen=True, slots=True)
class RateQuote:
    rate: Decimal
    as_of: date
    source: str


@dataclass(frozen=True, slots=True)
class FxStamp:
    amount_base: Decimal
    currency_base: str
    rate: Decimal
    rate_date: date
    source: str


class FXRateProvider(Protocol):
    def get_rate(self, *, base: str, quote: str, as_of: date) -> RateQuote: ...


class MissingFXRateError(RuntimeError):
    pass


def stamp_fx(
    transaction: ParsedTransaction,
    *,
    base_currency: str = "CAD",
    provider: FXRateProvider | None = None,
) -> FxStamp:
    """Stamp a row, using exact 1:1 arithmetic for Phase 0 CAD transactions."""

    base = base_currency.upper()
    native = transaction.currency_native.upper()
    if native == base:
        return FxStamp(
            amount_base=transaction.amount_native.quantize(Decimal("0.01")),
            currency_base=base,
            rate=Decimal("1"),
            rate_date=transaction.booked_date,
            source="identity",
        )
    if provider is None:
        raise MissingFXRateError(f"no FX provider configured for {native}/{base}")
    quote = provider.get_rate(base=native, quote=base, as_of=transaction.booked_date)
    return FxStamp(
        amount_base=(transaction.amount_native * quote.rate).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        ),
        currency_base=base,
        rate=quote.rate,
        rate_date=quote.as_of,
        source=quote.source,
    )


class StaticFXRateProvider:
    """Useful deterministic provider for tests and explicit seed data."""

    def __init__(self, rates: dict[tuple[str, str, date], RateQuote]) -> None:
        self._rates = rates

    def get_rate(self, *, base: str, quote: str, as_of: date) -> RateQuote:
        try:
            return self._rates[(base.upper(), quote.upper(), as_of)]
        except KeyError as exc:
            raise MissingFXRateError(f"rate not found for {base}/{quote} on {as_of}") from exc
