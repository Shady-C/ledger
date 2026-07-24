"""Deterministic base-currency stamping."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import ClassVar, Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote as url_quote
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

import psycopg
from psycopg.rows import dict_row

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


_RATE_QUANTUM = Decimal("0.00000001")
_MONEY_QUANTUM = Decimal("0.01")


class FXRateCache(Protocol):
    def find_rate(self, *, base: str, quote: str, as_of: date) -> RateQuote | None: ...

    def store_rate(self, *, base: str, quote: str, rate: RateQuote) -> None: ...


class HTTPTransport(Protocol):
    def __call__(self, url: str, timeout_seconds: float) -> bytes: ...


@dataclass(frozen=True, slots=True)
class FXRequirement:
    base: str
    quote: str
    as_of: date


class FXRebuildRepository(Protocol):
    def get_base_currency(self) -> str: ...

    def list_fx_requirements(self, *, target_currency: str) -> tuple[FXRequirement, ...]: ...

    def rebuild_base_currency(self, *, target_currency: str, max_staleness_days: int) -> int: ...


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
    rate = normalize_rate(quote.rate)
    return FxStamp(
        amount_base=(transaction.amount_native * rate).quantize(
            _MONEY_QUANTUM, rounding=ROUND_HALF_UP
        ),
        currency_base=base,
        rate=rate,
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


class FixtureFXRateProvider:
    """Explicit smoke-test rates; never selected unless provider mode is ``stub``."""

    _RATES: ClassVar[dict[tuple[str, str], Decimal]] = {
        ("USD", "CAD"): Decimal("1.35"),
        ("TZS", "CAD"): Decimal("0.00054"),
        ("CAD", "USD"): Decimal("0.74074074"),
        ("TZS", "USD"): Decimal("0.0004"),
        ("CAD", "TZS"): Decimal("1851.85185185"),
        ("USD", "TZS"): Decimal("2500"),
    }

    def get_rate(self, *, base: str, quote: str, as_of: date) -> RateQuote:
        base_code = _currency(base)
        quote_code = _currency(quote)
        if base_code == quote_code:
            return RateQuote(Decimal("1"), as_of, "identity")
        try:
            rate = self._RATES[(base_code, quote_code)]
        except KeyError as exc:
            raise MissingFXRateError(
                f"fixture rate not found for {base_code}/{quote_code}"
            ) from exc
        return RateQuote(rate, as_of, "fixture")


class FrankfurterFXRateProvider:
    """Frankfurter v2 client with strict historical-date validation."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        max_staleness_days: int | None = None,
        timeout_seconds: float = 10,
        transport: HTTPTransport | None = None,
    ) -> None:
        resolved_url = (base_url or os.getenv("FX_PROVIDER_URL") or "").strip()
        configured_url = (resolved_url or "https://api.frankfurter.dev/v2").rstrip("/")
        self._base_url = (
            configured_url if configured_url.endswith("/v2") else f"{configured_url}/v2"
        )
        if urlsplit(self._base_url).scheme not in {"http", "https"}:
            raise ValueError("FX_PROVIDER_URL must use http or https")
        configured_staleness = (
            max_staleness_days
            if max_staleness_days is not None
            else int(os.getenv("FX_MAX_STALENESS_DAYS", "7"))
        )
        if not 0 <= configured_staleness <= 7:
            raise ValueError("FX_MAX_STALENESS_DAYS must be between 0 and 7")
        if timeout_seconds <= 0:
            raise ValueError("FX provider timeout must be positive")
        self.max_staleness_days = configured_staleness
        self.timeout_seconds = timeout_seconds
        self._transport = transport or _get_url

    def get_rate(self, *, base: str, quote: str, as_of: date) -> RateQuote:
        base_code = _currency(base)
        quote_code = _currency(quote)
        if base_code == quote_code:
            return RateQuote(Decimal("1"), as_of, "identity")
        path = f"/rate/{url_quote(base_code, safe='')}/{url_quote(quote_code, safe='')}"
        url = f"{self._base_url}{path}?{urlencode({'date': as_of.isoformat()})}"
        try:
            raw = self._transport(url, self.timeout_seconds)
            payload = json.loads(raw)
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise MissingFXRateError(
                f"Frankfurter rate is unavailable for {base_code}/{quote_code}"
            ) from exc
        if not isinstance(payload, dict):
            raise MissingFXRateError("Frankfurter response must be an object")
        response_base = str(payload.get("base", "")).upper()
        response_quote = str(payload.get("quote", "")).upper()
        if (response_base, response_quote) != (base_code, quote_code):
            raise MissingFXRateError("Frankfurter returned a different currency pair")
        try:
            rate_date = date.fromisoformat(str(payload["date"]))
            rate = Decimal(str(payload["rate"]))
        except (KeyError, ValueError, ArithmeticError) as exc:
            raise MissingFXRateError("Frankfurter returned an invalid rate") from exc
        _validate_quote(
            rate=rate,
            rate_date=rate_date,
            requested=as_of,
            max_days=self.max_staleness_days,
        )
        return RateQuote(rate=normalize_rate(rate), as_of=rate_date, source="frankfurter-v2")


class CachedFXRateProvider:
    """Read-through cache that records the provider's actual observation date."""

    def __init__(self, *, cache: FXRateCache, upstream: FXRateProvider) -> None:
        self.cache = cache
        self.upstream = upstream

    def get_rate(self, *, base: str, quote: str, as_of: date) -> RateQuote:
        base_code = _currency(base)
        quote_code = _currency(quote)
        if base_code == quote_code:
            return RateQuote(Decimal("1"), as_of, "identity")
        cached = self.cache.find_rate(base=base_code, quote=quote_code, as_of=as_of)
        if cached is not None:
            return RateQuote(normalize_rate(cached.rate), cached.as_of, cached.source)
        resolved = self.upstream.get_rate(base=base_code, quote=quote_code, as_of=as_of)
        normalized = RateQuote(normalize_rate(resolved.rate), resolved.as_of, resolved.source)
        self.cache.store_rate(base=base_code, quote=quote_code, rate=normalized)
        return normalized


class PostgresFXRateCache:
    """Persistent nearest-prior FX cache backed by the existing ``fx_rate`` table."""

    def __init__(self, database_url: str, *, max_staleness_days: int = 7) -> None:
        if not database_url.strip():
            raise ValueError("database_url cannot be blank")
        if not 0 <= max_staleness_days <= 7:
            raise ValueError("max_staleness_days must be between 0 and 7")
        self._database_url = database_url
        self.max_staleness_days = max_staleness_days

    def find_rate(self, *, base: str, quote: str, as_of: date) -> RateQuote | None:
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                SELECT rate, as_of, source
                FROM fx_rate
                WHERE base = %s AND quote = %s
                  AND as_of BETWEEN %s AND %s
                ORDER BY as_of DESC
                LIMIT 1
                """,
                (
                    _currency(base),
                    _currency(quote),
                    as_of - timedelta(days=self.max_staleness_days),
                    as_of,
                ),
            ).fetchone()
        if row is None:
            return None
        return RateQuote(
            rate=cast(Decimal, row["rate"]),
            as_of=cast(date, row["as_of"]),
            source=str(row["source"]),
        )

    def store_rate(self, *, base: str, quote: str, rate: RateQuote) -> None:
        with psycopg.connect(self._database_url) as connection:
            connection.execute(
                """
                INSERT INTO fx_rate (base, quote, as_of, rate, source)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (base, quote, as_of) DO UPDATE
                SET rate = EXCLUDED.rate,
                    source = EXCLUDED.source,
                    fetched_at = now()
                """,
                (
                    _currency(base),
                    _currency(quote),
                    rate.as_of,
                    normalize_rate(rate.rate),
                    rate.source,
                ),
            )


class MemoryFXRateCache:
    def __init__(self, *, max_staleness_days: int = 7) -> None:
        if not 0 <= max_staleness_days <= 7:
            raise ValueError("max_staleness_days must be between 0 and 7")
        self.max_staleness_days = max_staleness_days
        self.rates: dict[tuple[str, str, date], RateQuote] = {}

    def find_rate(self, *, base: str, quote: str, as_of: date) -> RateQuote | None:
        candidates = [
            value
            for (candidate_base, candidate_quote, candidate_date), value in self.rates.items()
            if candidate_base == _currency(base)
            and candidate_quote == _currency(quote)
            and as_of - timedelta(days=self.max_staleness_days) <= candidate_date <= as_of
        ]
        return max(candidates, key=lambda value: value.as_of) if candidates else None

    def store_rate(self, *, base: str, quote: str, rate: RateQuote) -> None:
        self.rates[(_currency(base), _currency(quote), rate.as_of)] = rate


class FXRefreshService:
    def __init__(
        self,
        *,
        repository: FXRebuildRepository,
        provider: FXRateProvider,
    ) -> None:
        self.repository = repository
        self.provider = provider

    def run(self, payload: dict[str, object]) -> dict[str, object]:
        target_value = payload.get(
            "target_base_currency",
            payload.get("base_currency", self.repository.get_base_currency()),
        )
        if not isinstance(target_value, str):
            raise ValueError("fx_refresh base_currency must be a string")
        target = _currency(target_value)
        requirements = self.repository.list_fx_requirements(target_currency=target)
        quote_currencies: set[str] = set()
        for requirement in requirements:
            self.provider.get_rate(
                base=requirement.base,
                quote=requirement.quote,
                as_of=requirement.as_of,
            )
            quote_currencies.add(requirement.base)
        return {
            "base_currency": target,
            "quote_currencies": sorted(quote_currencies),
            "rates_stored": len(requirements),
        }


class BaseCurrencyRebuildService:
    def __init__(
        self,
        *,
        repository: FXRebuildRepository,
        provider: FXRateProvider,
        max_staleness_days: int = 7,
    ) -> None:
        if not 0 <= max_staleness_days <= 7:
            raise ValueError("max_staleness_days must be between 0 and 7")
        self.repository = repository
        self.refresh = FXRefreshService(repository=repository, provider=provider)
        self.max_staleness_days = max_staleness_days

    def run(self, payload: dict[str, object]) -> dict[str, object]:
        target_value = payload.get("target_base_currency", payload.get("base_currency"))
        if not isinstance(target_value, str):
            raise ValueError("base_currency_rebuild requires base_currency")
        target = _currency(target_value)
        previous = self.repository.get_base_currency()
        self.refresh.run({"target_base_currency": target})
        rebuilt = self.repository.rebuild_base_currency(
            target_currency=target,
            max_staleness_days=self.max_staleness_days,
        )
        return {
            "previous_base_currency": previous,
            "target_base_currency": target,
            "transactions_updated": rebuilt,
            "settings_updated": True,
        }


def _get_url(url: str, timeout_seconds: float) -> bytes:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "ledger/1"})
    with urlopen(request, timeout=timeout_seconds) as response:
        return cast(bytes, response.read())


def _currency(value: str) -> str:
    code = value.strip().upper()
    if len(code) != 3 or not code.isalpha():
        raise ValueError("currency must be a three-letter ISO-style code")
    return code


def _validate_quote(*, rate: Decimal, rate_date: date, requested: date, max_days: int) -> None:
    if not rate.is_finite() or rate <= 0:
        raise MissingFXRateError("FX rate must be positive and finite")
    if rate_date > requested:
        raise MissingFXRateError("FX rate cannot be newer than the requested date")
    if requested - rate_date > timedelta(days=max_days):
        raise MissingFXRateError("FX rate is too stale for the requested date")


def normalize_rate(rate: Decimal) -> Decimal:
    if not rate.is_finite() or rate <= 0:
        raise MissingFXRateError("FX rate must be positive and finite")
    normalized = rate.quantize(_RATE_QUANTUM, rounding=ROUND_HALF_UP)
    if normalized <= 0:
        raise MissingFXRateError("FX rate is below the supported eight-decimal scale")
    return normalized
