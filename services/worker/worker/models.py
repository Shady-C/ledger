"""Canonical worker-side models mirrored from the shared TypeScript contracts."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from worker.money import normalize_money


class Direction(StrEnum):
    """Semantic direction stored on a canonical transaction."""

    DEBIT = "debit"
    CREDIT = "credit"
    PAYMENT = "payment"
    FEE = "fee"
    REFUND = "refund"
    INTEREST = "interest"


class ParseStatus(StrEnum):
    READY = "ready"
    NEEDS_AI = "needs_ai"


class CategorySource(StrEnum):
    FALLBACK = "fallback"
    RULE = "rule"
    AI = "ai"
    USER_MERCHANT = "user_merchant"
    USER_TRANSACTION = "user_transaction"


class FlowType(StrEnum):
    SPEND = "spend"
    INCOME = "income"
    TRANSFER = "transfer"
    REFUND = "refund"
    FEE = "fee"


class AccountKind(StrEnum):
    CREDIT_CARD = "credit_card"
    CHEQUING = "chequing"
    SAVINGS = "savings"
    WALLET = "wallet"

    @property
    def is_asset(self) -> bool:
        return self in {self.CHEQUING, self.SAVINGS, self.WALLET}


class ParsedFile(BaseModel):
    """Raw object passed to adapter detection and parsing."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    name: str = Field(min_length=1)
    content: bytes
    content_type: str | None = None

    @property
    def extension(self) -> str:
        return PurePosixPath(self.name).suffix.lower()


class StatementMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    period_start: date | None = None
    period_end: date | None = None
    opening_balance: Decimal | None = None
    closing_balance: Decimal | None = None
    currency: str = "CAD"
    account_ref_masked: str | None = None

    @field_validator("opening_balance", "closing_balance")
    @classmethod
    def normalize_balances(cls, value: Decimal | None) -> Decimal | None:
        return normalize_money(value, field="statement balance") if value is not None else None

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        value = value.strip().upper()
        if len(value) != 3 or not value.isalpha():
            raise ValueError("currency must be a three-letter ISO-style code")
        return value


class ParsedTransaction(BaseModel):
    """Adapter output before FX, category, merchant, and dedup enrichment."""

    model_config = ConfigDict(frozen=True)

    booked_date: date
    posted_date: date | None = None
    description_raw: str = Field(min_length=1)
    amount_native: Decimal
    currency_native: str = "CAD"
    external_ref: str | None = None
    direction: Direction
    enrichment: dict[str, Any] = Field(default_factory=dict)

    @field_validator("amount_native")
    @classmethod
    def normalize_native_amount(cls, value: Decimal) -> Decimal:
        return normalize_money(value, field="native transaction amount")

    @field_validator("currency_native")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        value = value.strip().upper()
        if len(value) != 3 or not value.isalpha():
            raise ValueError("currency_native must be a three-letter ISO-style code")
        return value


class ParseResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    adapter: str
    rows: tuple[ParsedTransaction, ...] = ()
    statement: StatementMetadata = Field(default_factory=StatementMetadata)
    status: ParseStatus = ParseStatus.READY
    reason: str | None = None


class CanonicalTransaction(ParsedTransaction):
    """Fully deterministic row ready for persistence."""

    amount_base: Decimal
    currency_base: str
    fx_rate: Decimal
    fx_rate_date: date
    merchant_name: str
    merchant_key: str
    category_name: str
    category_kind: str
    dedup_hash: str
    category_source: CategorySource = CategorySource.FALLBACK
    category_confidence: float | None = Field(default=0, ge=0, le=1)


class FileIngestResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    file_key: str
    adapter: str
    status: str
    added: int = 0
    skipped: int = 0
    statement_id: str | None = None
    reconcile: dict[str, Any] | None = None
    reason: str | None = None
