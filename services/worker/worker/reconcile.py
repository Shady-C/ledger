"""Statement reconciliation and deterministic coverage-gap checks."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from worker.models import ParsedTransaction, StatementMetadata

_CENT = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    status: str
    opening_balance: Decimal | None
    transaction_total: Decimal
    calculated_closing: Decimal | None
    reported_closing: Decimal | None
    difference: Decimal | None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "status": self.status,
            "opening_balance": _text(self.opening_balance),
            "transaction_total": _text(self.transaction_total),
            "calculated_closing": _text(self.calculated_closing),
            "reported_closing": _text(self.reported_closing),
            "difference": _text(self.difference),
        }


def reconcile_statement(
    metadata: StatementMetadata, rows: Iterable[ParsedTransaction]
) -> ReconciliationResult:
    transaction_total = sum((row.amount_native for row in rows), start=Decimal("0")).quantize(_CENT)
    if metadata.opening_balance is None or metadata.closing_balance is None:
        return ReconciliationResult(
            status="pending",
            opening_balance=metadata.opening_balance,
            transaction_total=transaction_total,
            calculated_closing=None,
            reported_closing=metadata.closing_balance,
            difference=None,
        )
    calculated = (metadata.opening_balance + transaction_total).quantize(_CENT)
    reported = metadata.closing_balance.quantize(_CENT)
    difference = (calculated - reported).quantize(_CENT)
    return ReconciliationResult(
        status="ok" if difference == 0 else "mismatch",
        opening_balance=metadata.opening_balance.quantize(_CENT),
        transaction_total=transaction_total,
        calculated_closing=calculated,
        reported_closing=reported,
        difference=difference,
    )


@dataclass(frozen=True, slots=True)
class StatementPeriod:
    start: date
    end: date


def coverage_gaps(periods: Iterable[StatementPeriod]) -> tuple[StatementPeriod, ...]:
    ordered = sorted(periods, key=lambda period: (period.start, period.end))
    gaps: list[StatementPeriod] = []
    if not ordered:
        return ()
    covered_until = ordered[0].end
    for period in ordered[1:]:
        expected = covered_until + timedelta(days=1)
        if period.start > expected:
            gaps.append(StatementPeriod(expected, period.start - timedelta(days=1)))
        covered_until = max(covered_until, period.end)
    return tuple(gaps)


def _text(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None
