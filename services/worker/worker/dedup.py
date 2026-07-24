"""Stable transaction identity for repeat and overlapping statement ingestion."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import date
from decimal import Decimal


def normalize_description(description: str) -> str:
    normalized = unicodedata.normalize("NFKC", description).casefold()
    return re.sub(r"\s+", " ", normalized).strip()


def transaction_dedup_hash(
    *,
    account_id: str,
    booked_date: date,
    amount_native: Decimal,
    currency_native: str,
    description_raw: str,
    external_ref: str | None,
) -> str:
    """Hash exactly the canonical identity tuple documented for Phase 0."""

    amount = format(amount_native.quantize(Decimal("0.01")), "f")
    identity = "\x1f".join(
        (
            account_id,
            booked_date.isoformat(),
            amount,
            currency_native.upper(),
            normalize_description(description_raw),
            (external_ref or "").strip(),
        )
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()
