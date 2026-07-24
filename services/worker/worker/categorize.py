"""Deterministic, account-aware merchant normalization and category rules."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from worker.models import AccountKind, CategorySource, Direction, FlowType, ParsedTransaction


@dataclass(frozen=True, slots=True)
class Categorization:
    merchant_name: str
    merchant_key: str
    category_name: str
    category_kind: str
    confidence: float
    matched_rule: str | None
    source: CategorySource
    flow_type: FlowType


@dataclass(frozen=True, slots=True)
class CategoryRule:
    pattern: re.Pattern[str]
    name: str
    kind: str


_RULES = (
    CategoryRule(re.compile(r"\b(refund|reversal|credit)\b", re.I), "Refunds", "transfer"),
    CategoryRule(re.compile(r"\b(fee|interest)\b", re.I), "Fees & Interest", "fee"),
    CategoryRule(
        re.compile(r"\b(grocery|supermarket|market|loblaws|walmart|costco)\b", re.I),
        "Groceries",
        "spend",
    ),
    CategoryRule(
        re.compile(r"\b(cafe|coffee|restaurant|pizza|grill|bakery|doordash|uber eats)\b", re.I),
        "Dining",
        "spend",
    ),
    CategoryRule(
        re.compile(r"\b(uber|taxi|transit|metro|fuel|gas station)\b", re.I), "Transport", "spend"
    ),
    CategoryRule(
        re.compile(r"\b(hotel|airline|airways|flight|booking)\b", re.I), "Travel", "spend"
    ),
    CategoryRule(
        re.compile(r"\b(phone|internet|hydro|electric|utility)\b", re.I), "Utilities", "spend"
    ),
    CategoryRule(re.compile(r"\b(pharmacy|clinic|hospital|dental)\b", re.I), "Health", "spend"),
    CategoryRule(re.compile(r"\b(cinema|spotify|netflix|music)\b", re.I), "Entertainment", "spend"),
)

_PAYMENT = re.compile(r"\b(payment|autopay|thank you)\b", re.I)
_TRANSFER = re.compile(r"\b(transfer|e-?transfer|wire)\b", re.I)


def merchant_key(description: str) -> str:
    value = unicodedata.normalize("NFKC", description).casefold()
    value = re.sub(r"\b(?:ref|reference|txn)(?:\s*[#:]|\s+)[a-z0-9-]+\b", " ", value)
    value = re.sub(r"\d{2,}", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip() or "unknown"


def merchant_name(description: str) -> str:
    key = merchant_key(description)
    return " ".join(part.capitalize() for part in key.split())


def transaction_flow(
    transaction: ParsedTransaction,
    *,
    account_kind: AccountKind = AccountKind.CREDIT_CARD,
) -> FlowType:
    """Return the coarse flow used by learned merchant mappings.

    Flow is intentionally account-aware: a positive credit on an asset account
    is income, while the equivalent card credit is a refund/payment reduction.
    """

    description = transaction.description_raw
    if transaction.direction in {Direction.FEE, Direction.INTEREST}:
        return FlowType.FEE
    if transaction.direction is Direction.REFUND or re.search(
        r"\b(refund|reversal)\b", description, re.I
    ):
        return FlowType.REFUND
    if transaction.direction is Direction.PAYMENT or _PAYMENT.search(description):
        return FlowType.TRANSFER
    if _TRANSFER.search(description):
        return FlowType.TRANSFER
    if account_kind.is_asset and (
        transaction.direction is Direction.CREDIT or transaction.amount_native > 0
    ):
        return FlowType.INCOME
    if account_kind is AccountKind.CREDIT_CARD and transaction.amount_native < 0:
        return FlowType.REFUND
    return FlowType.SPEND


def categorize(
    transaction: ParsedTransaction,
    *,
    account_kind: AccountKind = AccountKind.CREDIT_CARD,
) -> Categorization:
    key = merchant_key(transaction.description_raw)
    name = merchant_name(transaction.description_raw)
    flow = transaction_flow(transaction, account_kind=account_kind)
    if _PAYMENT.search(transaction.description_raw):
        category = "Payments" if account_kind is AccountKind.CREDIT_CARD else "Transfers"
        return Categorization(
            name, key, category, "transfer", 1.0, _PAYMENT.pattern, CategorySource.RULE, flow
        )
    if _TRANSFER.search(transaction.description_raw):
        return Categorization(
            name,
            key,
            "Transfers",
            "transfer",
            1.0,
            _TRANSFER.pattern,
            CategorySource.RULE,
            flow,
        )
    for rule in _RULES:
        if rule.pattern.search(transaction.description_raw):
            return Categorization(
                name,
                key,
                rule.name,
                rule.kind,
                1.0,
                rule.pattern.pattern,
                CategorySource.RULE,
                flow,
            )
    if transaction.direction is Direction.PAYMENT:
        category = "Payments" if account_kind is AccountKind.CREDIT_CARD else "Transfers"
        return Categorization(
            name, key, category, "transfer", 1.0, "direction", CategorySource.RULE, flow
        )
    if transaction.direction is Direction.REFUND:
        return Categorization(
            name, key, "Refunds", "transfer", 1.0, "direction", CategorySource.RULE, flow
        )
    if transaction.direction in {Direction.FEE, Direction.INTEREST}:
        return Categorization(
            name,
            key,
            "Fees & Interest",
            "fee",
            1.0,
            "direction",
            CategorySource.RULE,
            flow,
        )
    if account_kind.is_asset and flow is FlowType.INCOME:
        return Categorization(
            name, key, "Income", "income", 1.0, "asset_credit", CategorySource.RULE, flow
        )
    return Categorization(name, key, "Other", "spend", 0.0, None, CategorySource.FALLBACK, flow)
