from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from worker.adapters.base import parse_decimal
from worker.categorize import categorize
from worker.dedup import transaction_dedup_hash
from worker.fx import MissingFXRateError, RateQuote, StaticFXRateProvider, stamp_fx
from worker.models import Direction, ParsedTransaction, StatementMetadata
from worker.reconcile import StatementPeriod, coverage_gaps, reconcile_statement


def transaction(**overrides: object) -> ParsedTransaction:
    values = {
        "booked_date": date(2026, 1, 2),
        "description_raw": "Synthetic Market 001",
        "amount_native": Decimal("12.34"),
        "currency_native": "CAD",
        "direction": Direction.DEBIT,
    }
    values.update(overrides)
    return ParsedTransaction(**values)


def test_cad_fx_is_exact_identity_and_never_requires_provider() -> None:
    row = transaction()
    stamp = stamp_fx(row)

    assert stamp.amount_base == Decimal("12.34")
    assert stamp.rate == Decimal("1")
    assert stamp.rate_date == row.booked_date
    assert stamp.source == "identity"


def test_non_cad_uses_explicit_dated_rate_and_bankers_rounding() -> None:
    booked = date(2026, 1, 2)
    row = transaction(currency_native="USD", amount_native=Decimal("10.01"))
    provider = StaticFXRateProvider(
        {("USD", "CAD", booked): RateQuote(Decimal("1.4"), booked, "seed")}
    )

    stamp = stamp_fx(row, provider=provider)

    assert stamp.amount_base == Decimal("14.01")
    assert stamp.rate == Decimal("1.4")
    assert stamp.source == "seed"


def test_native_money_rejects_rounding_and_normalizes_trailing_zeros() -> None:
    with pytest.raises(ValidationError, match="exactly representable at two decimals"):
        transaction(amount_native=Decimal("0.005"))

    normalized = transaction(amount_native=Decimal("12.3400"))

    assert normalized.amount_native == Decimal("12.34")
    assert normalized.amount_native.as_tuple().exponent == -2
    assert parse_decimal("12.3400") == Decimal("12.34")


@pytest.mark.parametrize(("field",), [("opening_balance",), ("closing_balance",)])
def test_statement_balances_reject_rounding(field: str) -> None:
    values = {
        "period_start": date(2026, 1, 1),
        "period_end": date(2026, 1, 31),
        field: Decimal("0.005"),
    }
    with pytest.raises(ValidationError, match="exactly representable at two decimals"):
        StatementMetadata(**values)


def test_non_cad_fails_closed_without_a_rate() -> None:
    with pytest.raises(MissingFXRateError):
        stamp_fx(transaction(currency_native="USD"))


def test_dedup_hash_normalizes_description_but_honors_reference() -> None:
    common = {
        "account_id": "account-1",
        "booked_date": date(2026, 1, 2),
        "amount_native": Decimal("12.340"),
        "currency_native": "cad",
    }
    first = transaction_dedup_hash(
        **common, description_raw="  SYNTHETIC   Café ", external_ref="REF-1"
    )
    same = transaction_dedup_hash(**common, description_raw="synthetic café", external_ref="REF-1")
    different = transaction_dedup_hash(
        **common, description_raw="synthetic café", external_ref="REF-2"
    )

    assert first == same
    assert first != different


def test_reconciliation_reports_exact_mismatch() -> None:
    metadata = StatementMetadata(
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        opening_balance=Decimal("100"),
        closing_balance=Decimal("111"),
    )
    result = reconcile_statement(metadata, [transaction(amount_native=Decimal("10"))])

    assert result.status == "mismatch"
    assert result.calculated_closing == Decimal("110.00")
    assert result.difference == Decimal("-1.00")


def test_coverage_gaps_ignore_overlaps_and_report_missing_days() -> None:
    gaps = coverage_gaps(
        [
            StatementPeriod(date(2026, 1, 1), date(2026, 1, 31)),
            StatementPeriod(date(2026, 1, 20), date(2026, 2, 10)),
            StatementPeriod(date(2026, 2, 13), date(2026, 2, 28)),
        ]
    )

    assert gaps == (StatementPeriod(date(2026, 2, 11), date(2026, 2, 12)),)


def test_category_rules_and_unknown_review_flag_source() -> None:
    known = categorize(transaction(description_raw="Synthetic Grocery Market"))
    unknown = categorize(transaction(description_raw="ZZZ Novel Vendor"))

    assert (known.category_name, known.confidence) == ("Groceries", 1.0)
    assert (unknown.category_name, unknown.confidence, unknown.matched_rule) == (
        "Other",
        0.0,
        None,
    )
