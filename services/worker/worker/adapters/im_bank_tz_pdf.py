"""Deterministic OCR adapter for I&M Bank Tanzania statement PDF layout v1.

The supplied export is a regular, image-only PDF. This adapter is deliberately
institution and layout specific: it uses local Tesseract OCR, validates the
stable header fingerprint, and proves every recognized amount against the
statement's running balances and printed totals before returning ledger rows.
It is not a general PDF or AI extraction fallback.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO

import pdfplumber

from worker.adapters.base import AdapterError, normalize_header
from worker.models import (
    AccountKind,
    Direction,
    ParsedFile,
    ParsedTransaction,
    ParseResult,
    StatementMetadata,
)
from worker.money import normalize_money

ADAPTER_NAME = "im_bank_tz_pdf_v1"
OCR_RESOLUTION_DPI = 300
MAX_PAGES = 50
MAX_RENDERED_PIXELS = 16_000_000
OCR_TIMEOUT_SECONDS = 45

_DATE_SHORT_PATTERN = r"\d{2}-\d{2}-\d{2}"
_DATE_LONG_PATTERN = r"\d{2}-\d{2}-\d{4}"
_MONEY_PATTERN = r"(?:\d{1,3}(?:,\s?\d{3})+|\d+)\.\d{2}"
_DATE_SHORT_RE = re.compile(rf"^{_DATE_SHORT_PATTERN}$")
_MONEY_RE = re.compile(_MONEY_PATTERN)
_PERIOD_RE = re.compile(
    rf"Statement\s+Period\s+({_DATE_LONG_PATTERN})\s+To\s+({_DATE_LONG_PATTERN})",
    re.IGNORECASE,
)
_CLOSING_RE = re.compile(
    rf"\bBalance\s+as\s+of\s+({_DATE_LONG_PATTERN})\s+"
    rf"({_MONEY_PATTERN})\s*(CR|DR)\b",
    re.IGNORECASE,
)
_OPENING_RE = re.compile(
    rf"^({_DATE_SHORT_PATTERN})\s+({_MONEY_PATTERN})\s*(CR|DR)\s+B\s*[/|]?\s*[FE]\b",
    re.IGNORECASE,
)
_TRANSACTION_RE = re.compile(
    rf"^({_DATE_SHORT_PATTERN})\s+({_DATE_SHORT_PATTERN})\s+(.+)$",
    re.IGNORECASE,
)
_RUNNING_BALANCE_RE = re.compile(
    rf"({_MONEY_PATTERN})\s*(CR|DR)\b",
    re.IGNORECASE,
)
_REFERENCE_RE = re.compile(
    rf"\bPRCR/[A-Z0-9@]+/{_DATE_LONG_PATTERN}\b",
    re.IGNORECASE,
)
_SECONDARY_REFERENCE_RE = re.compile(r"\bGS[A-Z0-9]{8,}\b", re.IGNORECASE)
_SEPARATE_NARRATIVE_TAIL_RE = re.compile(r"\S*/NRD\s*$", re.IGNORECASE)
_ACCOUNT_NUMBER_RE = re.compile(r"Account\s+Number\s+(\S+)", re.IGNORECASE)

_FINGERPRINT_TERMS = (
    "account name",
    "account number",
    "account type",
    "account currency",
    "tanzanian shilling",
    "statement period",
    "tran date",
    "withdrawls",
    "deposits",
    "transaction",
    "narrative",
)

OcrReader = Callable[[bytes, int | None], tuple[str, ...]]


@dataclass(slots=True)
class _RowEvidence:
    booked_date: date
    posted_date: date
    amount: Decimal
    running_balance: Decimal
    description_parts: list[str] = field(default_factory=list)


class ImBankTanzaniaPdfV1Adapter:
    """Parse the regular I&M Tanzania TZS statement image layout."""

    format = "pdf"
    name = ADAPTER_NAME

    def __init__(self, *, ocr_reader: OcrReader | None = None) -> None:
        self._ocr_reader = ocr_reader or _tesseract_pages

    def detect(self, file: ParsedFile) -> float:
        if file.extension != ".pdf" and not file.content.startswith(b"%PDF"):
            return 0.0
        try:
            pages = self._ocr_reader(file.content, 1)
        except (AdapterError, OSError, subprocess.SubprocessError):
            return 0.0
        if not pages:
            return 0.0
        normalized = normalize_header(pages[0])
        if all(term in normalized for term in _FINGERPRINT_TERMS):
            return 0.99
        return 0.0

    def parse(
        self,
        file: ParsedFile,
        *,
        account_kind: AccountKind = AccountKind.CHEQUING,
    ) -> ParseResult:
        if not account_kind.is_asset:
            raise AdapterError("I&M Tanzania layout v1 must be imported into an asset account")
        pages = self._ocr_reader(file.content, None)
        if not pages:
            raise AdapterError("I&M Tanzania PDF contains no OCR-readable pages")
        if not all(
            term in normalize_header(pages[0]) for term in _FINGERPRINT_TERMS
        ):
            raise AdapterError("I&M Tanzania PDF layout fingerprint did not match v1")

        text = "\n".join(pages)
        period_start, period_end = _statement_period(text)
        account_ref = _masked_account_reference(text)
        closing_date, closing_balance = _closing_balance(text)
        if closing_date != period_end:
            raise AdapterError("statement closing-balance date differs from period end")

        opening_balance, rows, totals = _table_evidence(
            pages,
            period_start=period_start,
            period_end=period_end,
        )
        if opening_balance + sum((row.amount for row in rows), Decimal("0")) != closing_balance:
            raise AdapterError("OCR transaction sum does not reconcile to the closing balance")
        if rows and rows[-1].running_balance != closing_balance:
            raise AdapterError("last OCR running balance differs from the closing balance")
        if not rows and opening_balance != closing_balance:
            raise AdapterError("zero-activity statement opening and closing balances differ")
        _validate_totals(rows, totals)

        parsed_rows = tuple(_canonical_row(row) for row in rows)
        return ParseResult(
            adapter=self.name,
            rows=parsed_rows,
            statement=StatementMetadata(
                period_start=period_start,
                period_end=period_end,
                opening_balance=opening_balance,
                closing_balance=closing_balance,
                currency="TZS",
                account_ref_masked=account_ref,
            ),
        )


def _tesseract_pages(content: bytes, max_pages: int | None) -> tuple[str, ...]:
    executable = shutil.which("tesseract")
    if executable is None:
        raise AdapterError(
            "I&M Tanzania image PDF parsing requires the local tesseract executable"
        )
    try:
        document = pdfplumber.open(BytesIO(content))
    except Exception as exc:
        raise AdapterError("I&M Tanzania PDF could not be opened") from exc
    with document:
        if not document.pages:
            raise AdapterError("I&M Tanzania PDF contains no pages")
        if len(document.pages) > MAX_PAGES:
            raise AdapterError(f"I&M Tanzania PDF exceeds the {MAX_PAGES}-page safety limit")
        page_limit = (
            len(document.pages)
            if max_pages is None
            else min(max_pages, len(document.pages))
        )
        pages: list[str] = []
        for page in document.pages[:page_limit]:
            try:
                image = page.to_image(
                    resolution=OCR_RESOLUTION_DPI,
                    antialias=True,
                ).original.convert("RGB")
            except Exception as exc:
                raise AdapterError("I&M Tanzania PDF page could not be rendered") from exc
            if image.width * image.height > MAX_RENDERED_PIXELS:
                raise AdapterError("I&M Tanzania PDF page exceeds the OCR pixel safety limit")
            encoded = BytesIO()
            image.save(encoded, format="PNG", optimize=False)
            try:
                completed = subprocess.run(
                    (
                        executable,
                        "stdin",
                        "stdout",
                        "-l",
                        "eng",
                        "--dpi",
                        str(OCR_RESOLUTION_DPI),
                        "--psm",
                        "6",
                    ),
                    input=encoded.getvalue(),
                    capture_output=True,
                    check=False,
                    timeout=OCR_TIMEOUT_SECONDS,
                )
            except subprocess.TimeoutExpired as exc:
                raise AdapterError("I&M Tanzania PDF OCR timed out") from exc
            if completed.returncode != 0:
                detail = completed.stderr.decode("utf-8", errors="replace").strip()
                raise AdapterError(f"I&M Tanzania PDF OCR failed: {detail or 'unknown error'}")
            text = completed.stdout.decode("utf-8", errors="strict").strip()
            if not text:
                raise AdapterError("I&M Tanzania PDF page produced no OCR text")
            pages.append(text)
        return tuple(pages)


def _statement_period(text: str) -> tuple[date, date]:
    matches = {
        (_long_date(match.group(1)), _long_date(match.group(2)))
        for match in _PERIOD_RE.finditer(_single_space(text))
    }
    if len(matches) != 1:
        raise AdapterError("I&M Tanzania PDF requires one consistent statement period")
    start, end = next(iter(matches))
    if start > end:
        raise AdapterError("statement period start is after its end")
    return start, end


def _masked_account_reference(text: str) -> str | None:
    match = _ACCOUNT_NUMBER_RE.search(_single_space(text))
    if match is None:
        return None
    digits = re.search(r"(\d{4,6})$", match.group(1))
    return f"••••{digits.group(1)[-4:]}" if digits is not None else None


def _closing_balance(text: str) -> tuple[date, Decimal]:
    matches = {
        (_long_date(match.group(1)), _signed_balance(match.group(2), match.group(3)))
        for match in _CLOSING_RE.finditer(_single_space(text))
    }
    if len(matches) != 1:
        raise AdapterError("I&M Tanzania PDF requires one consistent closing balance")
    return next(iter(matches))


def _table_evidence(
    pages: Sequence[str],
    *,
    period_start: date,
    period_end: date,
) -> tuple[Decimal, tuple[_RowEvidence, ...], tuple[Decimal, ...]]:
    opening_balance: Decimal | None = None
    current_balance: Decimal | None = None
    rows: list[_RowEvidence] = []
    totals: tuple[Decimal, ...] | None = None
    pending_description: list[str] = []
    in_table = False

    for page_text in pages:
        for raw_line in page_text.splitlines():
            line = _clean_line(raw_line)
            if not line:
                continue
            normalized = normalize_header(line)
            if "tran date" in normalized and "withdrawls" in normalized:
                in_table = True
                pending_description.clear()
                continue
            if not in_table:
                continue
            if normalized.startswith("totals"):
                page_totals = tuple(_money(value) for value in _MONEY_RE.findall(line))
                if totals is not None and totals != page_totals:
                    raise AdapterError("statement pages contain conflicting printed totals")
                totals = page_totals
                pending_description.clear()
                in_table = False
                continue
            if normalized.startswith(("date no narrative", "value ref", "tran date")):
                continue

            opening_match = _OPENING_RE.match(line)
            if opening_match is not None:
                opening_date = _short_date(opening_match.group(1))
                candidate = _signed_balance(opening_match.group(2), opening_match.group(3))
                if opening_date != period_start:
                    raise AdapterError("opening balance date differs from statement period start")
                if opening_balance is None:
                    opening_balance = candidate
                    current_balance = candidate
                elif candidate != current_balance:
                    raise AdapterError("carried-forward balance conflicts across statement pages")
                pending_description.clear()
                continue

            transaction_match = _TRANSACTION_RE.match(line)
            if transaction_match is not None:
                if current_balance is None:
                    raise AdapterError("transaction appeared before a carried-forward balance")
                booked_date = _short_date(transaction_match.group(1))
                posted_date = _short_date(transaction_match.group(2))
                body = transaction_match.group(3)
                balance_matches = tuple(_RUNNING_BALANCE_RE.finditer(body))
                if len(balance_matches) != 1:
                    raise AdapterError("transaction row requires one OCR running balance")
                balance_match = balance_matches[0]
                running_balance = _signed_balance(
                    balance_match.group(1), balance_match.group(2)
                )
                amount_values = _MONEY_RE.findall(body[: balance_match.start()])
                if len(amount_values) != 1:
                    raise AdapterError("transaction row requires one OCR debit or credit amount")
                source_magnitude = abs(_money(amount_values[0]))
                amount = normalize_money(
                    running_balance - current_balance,
                    field="I&M Tanzania running-balance delta",
                )
                if amount == 0 or abs(amount) != source_magnitude:
                    raise AdapterError(
                        "OCR debit or credit amount conflicts with the running-balance delta"
                    )
                if not period_start <= booked_date <= period_end:
                    raise AdapterError("transaction booking date is outside the statement period")
                trailing = _clean_line(body[balance_match.end() :])
                description_parts = [*pending_description]
                if trailing:
                    description_parts.append(trailing)
                rows.append(
                    _RowEvidence(
                        booked_date=booked_date,
                        posted_date=posted_date,
                        amount=amount,
                        running_balance=running_balance,
                        description_parts=description_parts,
                    )
                )
                pending_description.clear()
                current_balance = running_balance
                continue

            if re.match(rf"^{_DATE_SHORT_PATTERN}\b", line):
                raise AdapterError("OCR transaction row did not match the v1 layout")
            if rows and _SEPARATE_NARRATIVE_TAIL_RE.search(line):
                rows[-1].description_parts.append(line)
            elif not normalized.startswith(("date no narrative", "transaction narrative")):
                pending_description.append(line)

    if opening_balance is None:
        raise AdapterError("I&M Tanzania PDF opening balance was not recognized")
    if totals is None:
        raise AdapterError("I&M Tanzania PDF printed totals row was not recognized")
    return opening_balance, tuple(rows), totals


def _validate_totals(rows: Sequence[_RowEvidence], totals: tuple[Decimal, ...]) -> None:
    withdrawals = normalize_money(
        sum((-row.amount for row in rows if row.amount < 0), Decimal("0")),
        field="I&M Tanzania withdrawal total",
    )
    deposits = normalize_money(
        sum((row.amount for row in rows if row.amount > 0), Decimal("0")),
        field="I&M Tanzania deposit total",
    )
    expected = tuple(value for value in (withdrawals, deposits) if value != 0)
    if totals != expected:
        raise AdapterError("OCR transactions do not match the statement's printed totals")


def _canonical_row(row: _RowEvidence) -> ParsedTransaction:
    description = _single_space(" ".join(row.description_parts)).strip()
    if not description:
        raise AdapterError("I&M Tanzania transaction narrative is blank")
    normalized = normalize_header(description)
    if "interest" in normalized:
        direction = Direction.INTEREST
    elif row.amount < 0 and any(
        token in normalized for token in ("fee", "charge", "commission")
    ):
        direction = Direction.FEE
    else:
        direction = Direction.DEBIT if row.amount < 0 else Direction.CREDIT
    reference_match = _REFERENCE_RE.search(description) or _SECONDARY_REFERENCE_RE.search(
        description
    )
    return ParsedTransaction(
        booked_date=row.booked_date,
        posted_date=row.posted_date,
        description_raw=description,
        amount_native=row.amount,
        currency_native="TZS",
        external_ref=reference_match.group(0) if reference_match is not None else None,
        direction=direction,
        enrichment={"source_layout": ADAPTER_NAME},
    )


def _clean_line(value: str) -> str:
    return _single_space(value.replace("\u2013", "-").replace("\u2014", "-")).strip()


def _single_space(value: str) -> str:
    return re.sub(r"\s+", " ", value)


def _short_date(value: str) -> date:
    if _DATE_SHORT_RE.fullmatch(value) is None:
        raise AdapterError(f"invalid I&M Tanzania transaction date: {value!r}")
    try:
        return datetime.strptime(value, "%d-%m-%y").date()
    except ValueError as exc:
        raise AdapterError(f"invalid I&M Tanzania transaction date: {value!r}") from exc


def _long_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%d-%m-%Y").date()
    except ValueError as exc:
        raise AdapterError(f"invalid I&M Tanzania statement date: {value!r}") from exc


def _money(value: str) -> Decimal:
    cleaned = value.replace(",", "").replace(" ", "")
    try:
        parsed = Decimal(cleaned)
    except InvalidOperation as exc:
        raise AdapterError(f"invalid I&M Tanzania OCR amount: {value!r}") from exc
    return normalize_money(parsed, field="I&M Tanzania OCR amount")


def _signed_balance(value: str, side: str) -> Decimal:
    magnitude = abs(_money(value))
    return -magnitude if side.upper() == "DR" else magnitude
