"""Phase 0 deterministic merchant normalization and category rules."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from worker.models import Direction, ParsedTransaction


@dataclass(frozen=True, slots=True)
class Categorization:
    merchant_name: str
    merchant_key: str
    category_name: str
    category_kind: str
    confidence: float
    matched_rule: str | None


@dataclass(frozen=True, slots=True)
class CategoryRule:
    pattern: re.Pattern[str]
    name: str
    kind: str


_RULES = (
    CategoryRule(re.compile(r"\b(payment|autopay|thank you)\b", re.I), "Payments", "transfer"),
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


def merchant_key(description: str) -> str:
    value = unicodedata.normalize("NFKC", description).casefold()
    value = re.sub(r"\b(?:ref|reference|txn)(?:\s*[#:]|\s+)[a-z0-9-]+\b", " ", value)
    value = re.sub(r"\d{2,}", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip() or "unknown"


def merchant_name(description: str) -> str:
    key = merchant_key(description)
    return " ".join(part.capitalize() for part in key.split())


def categorize(transaction: ParsedTransaction) -> Categorization:
    key = merchant_key(transaction.description_raw)
    name = merchant_name(transaction.description_raw)
    for rule in _RULES:
        if rule.pattern.search(transaction.description_raw):
            return Categorization(name, key, rule.name, rule.kind, 1.0, rule.pattern.pattern)
    if transaction.direction in {Direction.PAYMENT, Direction.REFUND, Direction.CREDIT}:
        return Categorization(name, key, "Payments", "transfer", 1.0, "direction")
    if transaction.direction in {Direction.FEE, Direction.INTEREST}:
        return Categorization(name, key, "Fees & Interest", "fee", 1.0, "direction")
    return Categorization(name, key, "Other", "spend", 0.0, None)
