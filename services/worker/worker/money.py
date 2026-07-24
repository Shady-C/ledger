"""Exact fixed-precision validation for source monetary values."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

CENT = Decimal("0.01")


class MoneyPrecisionError(ValueError):
    """Raised when source money cannot be stored without rounding."""


def normalize_money(value: Decimal, *, field: str = "amount") -> Decimal:
    """Return a two-place Decimal, rejecting values that would require rounding."""

    if not value.is_finite():
        raise MoneyPrecisionError(f"{field} must be finite")
    try:
        normalized = value.quantize(CENT)
    except InvalidOperation as exc:
        raise MoneyPrecisionError(f"{field} is outside supported precision") from exc
    if value != normalized:
        raise MoneyPrecisionError(f"{field} must be exactly representable at two decimals")
    return normalized
