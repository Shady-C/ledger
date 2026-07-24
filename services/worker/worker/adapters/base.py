"""Adapter protocol and parsing primitives shared by deterministic adapters."""

from __future__ import annotations

import re
from collections.abc import Sequence, Set
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal, Protocol

from worker.models import AccountKind, Direction, ParsedFile, ParseResult, StatementMetadata
from worker.money import MoneyPrecisionError, normalize_money


class AdapterError(ValueError):
    """Raised when a recognized statement cannot be parsed safely."""


class Adapter(Protocol):
    format: str
    name: str

    def detect(self, file: ParsedFile) -> float: ...

    def parse(self, file: ParsedFile, *, account_kind: AccountKind) -> ParseResult: ...


_SPACE = re.compile(r"\s+")
_NON_HEADER = re.compile(r"[^a-z0-9]+")


def normalize_header(value: object) -> str:
    return _SPACE.sub(" ", _NON_HEADER.sub(" ", str(value or "").lower())).strip()


def locate_header_row(
    rows: Sequence[Sequence[object]],
    *,
    required_groups: Sequence[Set[str]],
) -> int | None:
    """Return the first row containing one alias from every required group."""

    for index, row in enumerate(rows):
        values = {normalize_header(cell) for cell in row if normalize_header(cell)}
        if all(values.intersection(group) for group in required_groups):
            return index
    return None


def resolve_unique_column(
    headers: Sequence[str],
    aliases: Sequence[str],
    *,
    field: str,
    required: bool = True,
) -> int | None:
    """Resolve exactly one source column without set-order-dependent precedence."""

    accepted = frozenset(aliases)
    matches = [(index, header) for index, header in enumerate(headers) if header in accepted]
    if len(matches) > 1:
        names = ", ".join(header for _index, header in matches)
        raise AdapterError(f"ambiguous {field} columns: {names}")
    if matches:
        return matches[0][0]
    if required:
        raise AdapterError(f"required {field} column missing (expected one of {list(aliases)})")
    return None


def parse_decimal(value: object, *, blank: Decimal | None = None) -> Decimal:
    if value is None or str(value).strip() == "":
        if blank is not None:
            return blank
        raise AdapterError("amount is blank")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int | float):
        return Decimal(str(value))
    text = str(value).strip()
    negative = text.startswith("(") and text.endswith(")")
    text = text.replace("(", "").replace(")", "")
    text = re.sub(r"(?i)\b(?:CAD|USD|TZS)\b", "", text)
    text = text.replace("$", "").replace(",", "").strip()
    try:
        result = Decimal(text)
    except InvalidOperation as exc:
        raise AdapterError(f"invalid amount: {value!r}") from exc
    return normalize_money(-result if negative else result)


_DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%b %d, %Y",
    "%B %d, %Y",
    "%d %b %Y",
)

SlashDateOrder = Literal["mdy", "dmy"]
_SLASH_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_YMD_SLASH_DATE = re.compile(r"^\d{4}/\d{1,2}/\d{1,2}$")


def parse_date(value: object, *, slash_order: SlashDateOrder | None = None) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if _SLASH_DATE.fullmatch(text):
        resolved_order = slash_order or infer_slash_date_order((text,))
        if resolved_order is None:
            raise AdapterError("slash-date order is unresolved")
        date_format = "%m/%d/%Y" if resolved_order == "mdy" else "%d/%m/%Y"
        try:
            return datetime.strptime(text, date_format).date()
        except ValueError as exc:
            raise AdapterError(f"invalid date: {value!r}") from exc
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise AdapterError(f"invalid date: {value!r}")


def infer_slash_date_order(values: Sequence[object]) -> SlashDateOrder | None:
    """Infer one slash order from evidence, rejecting ambiguity or disagreement."""

    evidence: set[SlashDateOrder] = set()
    ambiguous = False
    for value in values:
        if isinstance(value, date | datetime):
            continue
        text = str(value).strip()
        if _YMD_SLASH_DATE.fullmatch(text):
            continue
        match = _SLASH_DATE.fullmatch(text)
        if match is None:
            continue
        first, second = int(match.group(1)), int(match.group(2))
        if first > 12 and second > 12:
            raise AdapterError(f"invalid slash date: {text!r}")
        if first > 12:
            evidence.add("dmy")
        elif second > 12:
            evidence.add("mdy")
        else:
            ambiguous = True
    if len(evidence) > 1:
        raise AdapterError("conflicting MDY and DMY slash-date evidence")
    if ambiguous and not evidence:
        raise AdapterError("slash-date order is unresolved; include an unambiguous date")
    return next(iter(evidence), None)


def infer_direction(description: str, amount: Decimal) -> Direction:
    """Apply the locked credit-card sign convention without changing the amount."""

    normalized = normalize_header(description)
    if "interest" in normalized:
        return Direction.INTEREST
    if any(token in normalized for token in ("annual fee", "late fee", "service fee")):
        return Direction.FEE
    if any(token in normalized for token in ("payment", "autopay", "thank you")):
        return Direction.PAYMENT
    if any(token in normalized for token in ("refund", "reversal", "credit")):
        return Direction.REFUND if amount < 0 else Direction.CREDIT
    return Direction.DEBIT if amount >= 0 else Direction.CREDIT


_PERIOD_DATE = re.compile(
    r"(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|"
    r"\d{1,2}/\d{1,2}/\d{4}|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},\s+\d{4})",
    re.IGNORECASE,
)


def statement_period_date_values(rows: Sequence[Sequence[object]]) -> tuple[str, ...]:
    candidates: list[str] = []
    for row in rows:
        cells = [str(cell).strip() for cell in row if cell is not None and str(cell).strip()]
        joined = " ".join(cells)
        normalized = normalize_header(joined)
        if "statement period" in normalized or "billing period" in normalized:
            candidates.extend(_PERIOD_DATE.findall(joined))
    return tuple(candidates)


def extract_statement_metadata(
    rows: Sequence[Sequence[object]],
    *,
    slash_date_order: SlashDateOrder | None = None,
) -> StatementMetadata:
    """Read common statement labels from preamble/table rows without guessing totals."""

    period_start: date | None = None
    period_end: date | None = None
    opening: Decimal | None = None
    closing: Decimal | None = None
    currency = "CAD"
    account_ref: str | None = None
    period_values = statement_period_date_values(rows)
    resolved_slash_order = slash_date_order or infer_slash_date_order(period_values)

    for row in rows:
        cells = [str(cell).strip() for cell in row if cell is not None and str(cell).strip()]
        if not cells:
            continue
        joined = " ".join(cells)
        normalized = normalize_header(joined)
        if "statement period" in normalized or "billing period" in normalized:
            candidates = _PERIOD_DATE.findall(joined)
            if len(candidates) >= 2:
                period_start = parse_date(candidates[0], slash_order=resolved_slash_order)
                period_end = parse_date(candidates[1], slash_order=resolved_slash_order)
        if "opening balance" in normalized:
            opening = _amount_after_label(cells, "opening balance")
        if "closing balance" in normalized or "new balance" in normalized:
            closing = _amount_after_label(cells, "closing balance", "new balance")
        currency_match = re.search(r"\b(CAD|USD|TZS)\b", joined, re.IGNORECASE)
        if currency_match and ("currency" in normalized or "balance" in normalized):
            currency = currency_match.group(1).upper()
        if "account" in normalized and (match := re.search(r"\d{4,}", joined)):
            account_ref = f"••••{match.group(0)[-4:]}"

    return StatementMetadata(
        period_start=period_start,
        period_end=period_end,
        opening_balance=opening,
        closing_balance=closing,
        currency=currency,
        account_ref_masked=account_ref,
    )


def metadata_with_row_dates(
    metadata: StatementMetadata, transaction_dates: Sequence[date]
) -> StatementMetadata:
    """Use transaction bounds only when a statement omits an explicit period."""

    if not transaction_dates:
        return metadata
    return metadata.model_copy(
        update={
            "period_start": metadata.period_start or min(transaction_dates),
            "period_end": metadata.period_end or max(transaction_dates),
        }
    )


def _amount_after_label(cells: Sequence[str], *labels: str) -> Decimal | None:
    for index, cell in enumerate(cells):
        normalized = normalize_header(cell)
        for label in labels:
            if label in normalized:
                suffix = re.sub(label, "", cell, flags=re.IGNORECASE).strip(" :")
                candidates = ([suffix] if suffix else []) + list(cells[index + 1 :])
                for candidate in candidates:
                    try:
                        return parse_decimal(candidate)
                    except MoneyPrecisionError:
                        raise
                    except AdapterError:
                        continue
    return None
