"""Canonical worker-side models mirrored from the shared TypeScript contracts."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
    original_amount: Decimal | None = None
    original_currency: str | None = None
    fx_fee_amount_native: Decimal | None = None
    is_fx_fee: bool = False
    external_ref: str | None = None
    direction: Direction
    enrichment: dict[str, Any] = Field(default_factory=dict)

    @field_validator("amount_native")
    @classmethod
    def normalize_native_amount(cls, value: Decimal) -> Decimal:
        return normalize_money(value, field="native transaction amount")

    @field_validator("original_amount")
    @classmethod
    def normalize_original_amount(cls, value: Decimal | None) -> Decimal | None:
        return (
            normalize_money(value, field="original transaction amount")
            if value is not None
            else None
        )

    @field_validator("fx_fee_amount_native")
    @classmethod
    def normalize_inline_fx_fee(cls, value: Decimal | None) -> Decimal | None:
        if value is None:
            return None
        normalized = normalize_money(value, field="native FX fee amount")
        if normalized < 0:
            raise ValueError("fx_fee_amount_native must be a non-negative component")
        return normalized

    @field_validator("currency_native", "original_currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().upper()
        if len(value) != 3 or not value.isalpha():
            raise ValueError("currency must be a three-letter ISO-style code")
        return value

    @model_validator(mode="after")
    def validate_currency_layers(self) -> ParsedTransaction:
        original_amount = self.original_amount
        if (original_amount is None) != (self.original_currency is None):
            raise ValueError("original_amount and original_currency must be supplied together")
        if (
            original_amount is not None
            and original_amount != 0
            and self.amount_native != 0
            and (original_amount < 0) != (self.amount_native < 0)
        ):
            raise ValueError("original and posted amounts must use the same flow sign")
        if self.is_fx_fee and self.fx_fee_amount_native is not None:
            raise ValueError("a standalone FX-fee row cannot also contain an inline FX fee")
        if (
            self.fx_fee_amount_native is not None
            and self.fx_fee_amount_native > abs(self.amount_native)
        ):
            raise ValueError("an inline FX fee cannot exceed the posted amount")
        if self.is_fx_fee and self.direction is not Direction.FEE:
            raise ValueError("a standalone FX-fee row must use the fee direction")
        return self


class ParseResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    adapter: str
    rows: tuple[ParsedTransaction, ...] = ()
    statement: StatementMetadata = Field(default_factory=StatementMetadata)
    status: ParseStatus = ParseStatus.READY
    reason: str | None = None


class CanonicalTransaction(ParsedTransaction):
    """Fully deterministic row ready for persistence."""

    amount_base: Decimal | None
    currency_base: str
    fx_rate: Decimal | None
    fx_rate_date: date | None
    merchant_name: str
    merchant_key: str
    category_name: str
    category_kind: str
    dedup_hash: str
    category_source: CategorySource = CategorySource.FALLBACK
    category_confidence: float | None = Field(default=0, ge=0, le=1)

    @field_validator("amount_base")
    @classmethod
    def normalize_base_amount(cls, value: Decimal | None) -> Decimal | None:
        return normalize_money(value, field="CAD reporting amount") if value is not None else None

    @field_validator("currency_base")
    @classmethod
    def reporting_currency_is_fixed(cls, value: str) -> str:
        code = value.strip().upper()
        if code != "CAD":
            raise ValueError("Phase 2 reporting currency is fixed to CAD")
        return code

    @model_validator(mode="after")
    def validate_reporting_layer(self) -> CanonicalTransaction:
        valued = (self.amount_base, self.fx_rate, self.fx_rate_date)
        if self.currency_native == "CAD":
            if (
                self.amount_base != self.amount_native
                or self.fx_rate != Decimal("1")
                or self.fx_rate_date is None
            ):
                raise ValueError("CAD-native transactions require an identity reporting valuation")
            return self
        if all(value is None for value in valued):
            return self
        if any(value is None for value in valued):
            raise ValueError("reporting amount, rate, and rate date must be present together")
        assert self.amount_base is not None
        assert self.fx_rate is not None
        assert self.fx_rate_date is not None
        if self.fx_rate <= 0:
            raise ValueError("FX rate must be positive")
        expected_base = (self.amount_native * self.fx_rate).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
        if self.amount_base != expected_base:
            raise ValueError("CAD reporting amount must equal posted amount times the FX rate")
        staleness_days = (self.booked_date - self.fx_rate_date).days
        if not 0 <= staleness_days <= 7:
            raise ValueError("FX rate date must be booked date or at most seven prior days")
        return self


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
