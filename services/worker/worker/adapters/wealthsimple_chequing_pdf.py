"""Deterministic Wealthsimple CAD chequing statement PDF adapter v1.

The supported export is a text PDF with stable, positioned columns.  The
adapter deliberately recognizes only that institution/layout combination and
proves every signed amount against the printed running and summary balances.
It does not OCR, call an external provider, or guess at unfamiliar PDFs.
"""

from __future__ import annotations

import re
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

ADAPTER_NAME = "wealthsimple_chequing_pdf_v1"
MAX_PAGES = 20
LINE_TOLERANCE = 2.0
MAX_CONTINUATION_GAP = 15.0

_DATE_COLUMN_END = 75.0
_POSTED_DATE_COLUMN_END = 135.0
_DESCRIPTION_COLUMN_END = 315.0
_AMOUNT_COLUMN_END = 385.0

_MONTH_PATTERN = (
    r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?"
)
_PERIOD_RE = re.compile(
    rf"^({_MONTH_PATTERN})\s+(\d{{1,2}})\s*[-\u2013\u2014]\s*"
    rf"({_MONTH_PATTERN})\s+(\d{{1,2}}),\s*(\d{{4}})$",
    re.IGNORECASE,
)
_SUMMARY_RE = re.compile(
    rf"^your\s+({_MONTH_PATTERN})\s+summary\s+({_MONTH_PATTERN})\s+"
    rf"(\d{{1,2}})\s+balance\s+({_MONTH_PATTERN})\s+(\d{{1,2}})\s+balance$",
    re.IGNORECASE,
)
_ACCOUNT_RE = re.compile(r"^account\s+number:\s*([0-9][0-9 -]{3,})$", re.IGNORECASE)
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_DATE_SEARCH_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_MONEY_RE = re.compile(
    r"^(?P<negative>[-\u2013\u2212])?\$(?P<amount>(?:0|[1-9]\d{0,2}(?:,\d{3})*)\.\d{2})$"
)
_PAGE_COUNTER_RE = re.compile(r"^page\s+(\d+)\s+of\s+(\d+)(?:\s+.*)?$", re.IGNORECASE)
_INTEREST_RE = re.compile(r"\binterest\b")
_FEE_RE = re.compile(
    r"\b(?:fee|fees|commission|commissions)\b|"
    r"\b(?:account|bank|monthly|service)\s+charges?\b"
)
_ACTIVITY_HEADER = "date posted date description amount cad balance cad"
_FINGERPRINT_TERMS = (
    "wealthsimple",
    "chequing monthly statement",
    "account number",
    "activity",
    _ACTIVITY_HEADER,
)


@dataclass(frozen=True, slots=True)
class _PositionedWord:
    text: str
    x0: float
    x1: float
    top: float


@dataclass(frozen=True, slots=True)
class _PositionedLine:
    top: float
    words: tuple[_PositionedWord, ...]

    @property
    def text(self) -> str:
        return _single_space(" ".join(word.text for word in self.words))


@dataclass(slots=True)
class _RowEvidence:
    booked_date: date
    posted_date: date
    amount: Decimal
    running_balance: Decimal
    description_parts: list[str] = field(default_factory=list)


WordReader = Callable[
    [bytes, int | None],
    tuple[tuple[_PositionedWord, ...], ...],
]


class WealthsimpleChequingPdfV1Adapter:
    """Parse the versioned Wealthsimple CAD chequing monthly-statement layout."""

    format = "pdf"
    name = ADAPTER_NAME

    def __init__(self, *, word_reader: WordReader | None = None) -> None:
        self._word_reader = word_reader or _pdf_words

    def detect(self, file: ParsedFile) -> float:
        if file.extension != ".pdf" and not file.content.startswith(b"%PDF"):
            return 0.0
        try:
            pages = self._word_reader(file.content, 1)
        except (AdapterError, OSError):
            return 0.0
        if not pages or not pages[0]:
            return 0.0
        return 0.99 if _fingerprint_matches(_positioned_lines(pages[0])) else 0.0

    def parse(
        self,
        file: ParsedFile,
        *,
        account_kind: AccountKind = AccountKind.CHEQUING,
    ) -> ParseResult:
        if not account_kind.is_asset:
            raise AdapterError(
                "Wealthsimple chequing layout v1 must be imported into an asset account"
            )
        pages = self._word_reader(file.content, None)
        if not pages or not any(pages):
            raise AdapterError("Wealthsimple chequing PDF contains no positioned text")
        if len(pages) > MAX_PAGES:
            raise AdapterError(
                f"Wealthsimple chequing PDF exceeds the {MAX_PAGES}-page safety limit"
            )
        page_lines = tuple(_positioned_lines(page) for page in pages)
        if not _fingerprint_matches(page_lines[0]):
            raise AdapterError("Wealthsimple chequing PDF layout fingerprint did not match v1")
        _validate_page_sequence(page_lines)

        period_start, period_end = _statement_period(page_lines[0])
        account_ref = _masked_account_reference(page_lines[0])
        opening_balance, closing_balance = _summary_balances(
            page_lines[0],
            period_start=period_start,
            period_end=period_end,
        )
        rows = _transaction_evidence(
            page_lines,
            period_start=period_start,
            period_end=period_end,
        )
        _validate_balances(
            rows,
            opening_balance=opening_balance,
            closing_balance=closing_balance,
        )

        return ParseResult(
            adapter=self.name,
            rows=tuple(_canonical_row(row) for row in rows),
            statement=StatementMetadata(
                period_start=period_start,
                period_end=period_end,
                opening_balance=opening_balance,
                closing_balance=closing_balance,
                currency="CAD",
                account_ref_masked=account_ref,
            ),
        )


def _pdf_words(
    content: bytes,
    max_pages: int | None,
) -> tuple[tuple[_PositionedWord, ...], ...]:
    try:
        document = pdfplumber.open(BytesIO(content))
    except Exception as exc:
        raise AdapterError("Wealthsimple chequing PDF could not be opened") from exc
    with document:
        if not document.pages:
            raise AdapterError("Wealthsimple chequing PDF contains no pages")
        if len(document.pages) > MAX_PAGES:
            raise AdapterError(
                f"Wealthsimple chequing PDF exceeds the {MAX_PAGES}-page safety limit"
            )
        page_limit = (
            len(document.pages) if max_pages is None else min(max_pages, len(document.pages))
        )
        pages: list[tuple[_PositionedWord, ...]] = []
        for page in document.pages[:page_limit]:
            try:
                extracted = page.extract_words(
                    x_tolerance=1,
                    y_tolerance=2,
                    keep_blank_chars=False,
                    use_text_flow=False,
                )
                words = tuple(
                    _PositionedWord(
                        text=str(word["text"]),
                        x0=float(word["x0"]),
                        x1=float(word["x1"]),
                        top=float(word["top"]),
                    )
                    for word in extracted
                )
            except Exception as exc:
                raise AdapterError(
                    "Wealthsimple chequing PDF positioned text could not be extracted"
                ) from exc
            pages.append(words)
        return tuple(pages)


def _positioned_lines(words: Sequence[_PositionedWord]) -> tuple[_PositionedLine, ...]:
    grouped: list[list[_PositionedWord]] = []
    tops: list[float] = []
    for word in sorted(words, key=lambda candidate: (candidate.top, candidate.x0)):
        if not grouped or abs(word.top - tops[-1]) > LINE_TOLERANCE:
            grouped.append([word])
            tops.append(word.top)
            continue
        grouped[-1].append(word)
        tops[-1] = sum(candidate.top for candidate in grouped[-1]) / len(grouped[-1])
    return tuple(
        _PositionedLine(
            top=top,
            words=tuple(sorted(line_words, key=lambda candidate: candidate.x0)),
        )
        for top, line_words in zip(tops, grouped, strict=True)
    )


def _fingerprint_matches(lines: Sequence[_PositionedLine]) -> bool:
    normalized = " ".join(normalize_header(line.text) for line in lines)
    return all(term in normalized for term in _FINGERPRINT_TERMS) and re.search(
        rf"\byour ({_MONTH_PATTERN}) summary\b",
        normalized,
        re.IGNORECASE,
    ) is not None


def _validate_page_sequence(page_lines: Sequence[Sequence[_PositionedLine]]) -> None:
    page_count = len(page_lines)
    for expected_page, lines in enumerate(page_lines, 1):
        counters = [
            match
            for line in lines
            if (match := _PAGE_COUNTER_RE.fullmatch(normalize_header(line.text)))
        ]
        if len(counters) != 1:
            raise AdapterError(
                "each Wealthsimple chequing PDF page requires one page counter"
            )
        printed_page, printed_total = (int(value) for value in counters[0].groups())
        if printed_page != expected_page or printed_total != page_count:
            raise AdapterError(
                "printed page numbering does not match the PDF page sequence"
            )


def _statement_period(lines: Sequence[_PositionedLine]) -> tuple[date, date]:
    matches = [match for line in lines if (match := _PERIOD_RE.fullmatch(line.text))]
    if len(matches) != 1:
        raise AdapterError("Wealthsimple chequing PDF requires one statement period")
    match = matches[0]
    start_month = _month_number(match.group(1))
    end_month = _month_number(match.group(3))
    end_year = int(match.group(5))
    start_year = end_year - 1 if start_month > end_month else end_year
    try:
        start = date(start_year, start_month, int(match.group(2)))
        end = date(end_year, end_month, int(match.group(4)))
    except ValueError as exc:
        raise AdapterError("Wealthsimple chequing PDF statement period is invalid") from exc
    if start > end:
        raise AdapterError("statement period start is after its end")
    return start, end


def _masked_account_reference(lines: Sequence[_PositionedLine]) -> str:
    matches = [match for line in lines if (match := _ACCOUNT_RE.fullmatch(line.text))]
    if len(matches) != 1:
        raise AdapterError("Wealthsimple chequing PDF requires one account number")
    digits = re.sub(r"\D", "", matches[0].group(1))
    if len(digits) < 4:
        raise AdapterError("Wealthsimple chequing PDF account number is invalid")
    return f"••••{digits[-4:]}"


def _summary_balances(
    lines: Sequence[_PositionedLine],
    *,
    period_start: date,
    period_end: date,
) -> tuple[Decimal, Decimal]:
    summary_indexes = [
        index
        for index, line in enumerate(lines)
        if _SUMMARY_RE.fullmatch(normalize_header(line.text))
    ]
    if len(summary_indexes) != 1:
        raise AdapterError("Wealthsimple chequing PDF requires one monthly summary")
    summary_index = summary_indexes[0]
    match = _SUMMARY_RE.fullmatch(normalize_header(lines[summary_index].text))
    assert match is not None
    summary_month = _month_number(match.group(1))
    opening_date = _month_day_date(
        match.group(2),
        match.group(3),
        period_start=period_start,
        period_end=period_end,
    )
    closing_date = _month_day_date(
        match.group(4),
        match.group(5),
        period_start=period_start,
        period_end=period_end,
    )
    if (
        summary_month != period_end.month
        or opening_date != period_start
        or closing_date != period_end
    ):
        raise AdapterError("monthly summary dates differ from the statement period")

    summary_line = lines[summary_index]
    balance_lines = [
        line
        for line in lines[summary_index + 1 :]
        if 0 < line.top - summary_line.top <= 35
        and len(line.words) == 2
        and all(_MONEY_RE.fullmatch(word.text) for word in line.words)
    ]
    if len(balance_lines) != 1:
        raise AdapterError("monthly summary requires one opening and closing balance row")
    opening_word, closing_word = balance_lines[0].words
    if not (
        260 <= opening_word.x0 < 350
        and closing_word.x0 >= 350
        and opening_word.x1 < closing_word.x0
    ):
        raise AdapterError("monthly summary balances do not match the v1 layout")
    return _money(opening_word.text), _money(closing_word.text)


def _transaction_evidence(
    page_lines: Sequence[Sequence[_PositionedLine]],
    *,
    period_start: date,
    period_end: date,
) -> tuple[_RowEvidence, ...]:
    rows: list[_RowEvidence] = []
    previous_booked_date: date | None = None

    for lines in page_lines:
        header_indexes = [
            index
            for index, line in enumerate(lines)
            if normalize_header(line.text) == _ACTIVITY_HEADER
        ]
        if len(header_indexes) != 1:
            raise AdapterError(
                "each Wealthsimple chequing PDF page requires one unambiguous activity header"
            )
        can_continue = False
        previous_line_top: float | None = None
        for line in lines[header_indexes[0] + 1 :]:
            bands = _column_bands(line)
            date_text = _band_text(bands[0])
            if _ISO_DATE_RE.fullmatch(date_text):
                row = _transaction_row(
                    bands,
                    period_start=period_start,
                    period_end=period_end,
                )
                if previous_booked_date is not None and row.booked_date < previous_booked_date:
                    raise AdapterError("transaction booking dates are not chronological")
                rows.append(row)
                previous_booked_date = row.booked_date
                can_continue = True
                previous_line_top = line.top
                continue

            only_description = bool(bands[2]) and not any(
                bands[index] for index in (0, 1, 3, 4)
            )
            if (
                only_description
                and can_continue
                and rows
                and previous_line_top is not None
                and 0 < line.top - previous_line_top <= MAX_CONTINUATION_GAP
            ):
                rows[-1].description_parts.append(_band_text(bands[2]))
                previous_line_top = line.top
                continue

            can_continue = False
            previous_line_top = None
            if _has_unparsed_transaction_evidence(line, bands):
                raise AdapterError(
                    "activity section contains transaction-like content outside the v1 columns"
                )

    return tuple(rows)


def _transaction_row(
    bands: tuple[
        tuple[_PositionedWord, ...],
        tuple[_PositionedWord, ...],
        tuple[_PositionedWord, ...],
        tuple[_PositionedWord, ...],
        tuple[_PositionedWord, ...],
    ],
    *,
    period_start: date,
    period_end: date,
) -> _RowEvidence:
    booked_date = _iso_date(_band_text(bands[0]), field="booking")
    posted_date = _iso_date(_band_text(bands[1]), field="posted")
    if not period_start <= booked_date <= period_end:
        raise AdapterError("transaction booking date is outside the statement period")
    if not period_start <= posted_date <= period_end:
        raise AdapterError("transaction posted date is outside the statement period")
    description = _band_text(bands[2])
    if not description:
        raise AdapterError("transaction description is blank")
    amount_text = _band_text(bands[3])
    balance_text = _band_text(bands[4])
    if _MONEY_RE.fullmatch(amount_text) is None:
        raise AdapterError("transaction row requires one signed CAD amount")
    if _MONEY_RE.fullmatch(balance_text) is None:
        raise AdapterError("transaction row requires one CAD running balance")
    amount = _money(amount_text)
    if amount == 0:
        raise AdapterError("transaction amount cannot be zero")
    return _RowEvidence(
        booked_date=booked_date,
        posted_date=posted_date,
        amount=amount,
        running_balance=_money(balance_text),
        description_parts=[description],
    )


def _column_bands(
    line: _PositionedLine,
) -> tuple[
    tuple[_PositionedWord, ...],
    tuple[_PositionedWord, ...],
    tuple[_PositionedWord, ...],
    tuple[_PositionedWord, ...],
    tuple[_PositionedWord, ...],
]:
    bands: list[list[_PositionedWord]] = [[], [], [], [], []]
    for word in line.words:
        if word.x0 < _DATE_COLUMN_END:
            index = 0
        elif word.x0 < _POSTED_DATE_COLUMN_END:
            index = 1
        elif word.x0 < _DESCRIPTION_COLUMN_END:
            index = 2
        elif word.x0 < _AMOUNT_COLUMN_END:
            index = 3
        else:
            index = 4
        bands[index].append(word)
    return tuple(tuple(band) for band in bands)  # type: ignore[return-value]


def _has_unparsed_transaction_evidence(
    line: _PositionedLine,
    bands: tuple[
        tuple[_PositionedWord, ...],
        tuple[_PositionedWord, ...],
        tuple[_PositionedWord, ...],
        tuple[_PositionedWord, ...],
        tuple[_PositionedWord, ...],
    ],
) -> bool:
    if _ISO_DATE_SEARCH_RE.search(line.text):
        return True
    if any(_MONEY_RE.fullmatch(word.text) for word in line.words):
        return True
    # Content wholly inside the table's description/amount/balance region is
    # not legal/footer prose and must not disappear silently as a partial row.
    return bool(line.words) and not bands[0] and not bands[1]


def _validate_balances(
    rows: Sequence[_RowEvidence],
    *,
    opening_balance: Decimal,
    closing_balance: Decimal,
) -> None:
    previous = opening_balance
    for row in rows:
        expected = normalize_money(
            previous + row.amount,
            field="Wealthsimple chequing running-balance delta",
        )
        if expected != row.running_balance:
            raise AdapterError(
                "transaction amount conflicts with the printed running-balance delta"
            )
        previous = row.running_balance

    transaction_total = normalize_money(
        sum((row.amount for row in rows), Decimal("0")),
        field="Wealthsimple chequing transaction total",
    )
    if opening_balance + transaction_total != closing_balance:
        raise AdapterError("transactions do not reconcile to the printed closing balance")
    if rows and rows[-1].running_balance != closing_balance:
        raise AdapterError("last running balance differs from the printed closing balance")
    if not rows and opening_balance != closing_balance:
        raise AdapterError("zero-activity statement opening and closing balances differ")


def _canonical_row(row: _RowEvidence) -> ParsedTransaction:
    description = _single_space(" ".join(row.description_parts)).strip()
    if not description:
        raise AdapterError("transaction description is blank")
    normalized = normalize_header(description)
    if _INTEREST_RE.search(normalized):
        direction = Direction.INTEREST
    elif row.amount < 0 and _FEE_RE.search(normalized):
        direction = Direction.FEE
    else:
        direction = Direction.DEBIT if row.amount < 0 else Direction.CREDIT
    return ParsedTransaction(
        booked_date=row.booked_date,
        posted_date=row.posted_date,
        description_raw=description,
        amount_native=row.amount,
        currency_native="CAD",
        direction=direction,
        enrichment={"source_layout": ADAPTER_NAME},
    )


def _month_day_date(
    month: str,
    day: str,
    *,
    period_start: date,
    period_end: date,
) -> date:
    month_number = _month_number(month)
    year = period_end.year if month_number <= period_end.month else period_start.year
    try:
        return date(year, month_number, int(day))
    except ValueError as exc:
        raise AdapterError("monthly summary contains an invalid date") from exc


def _month_number(value: str) -> int:
    try:
        return datetime.strptime(value[:3].title(), "%b").month
    except ValueError as exc:
        raise AdapterError(f"invalid month in Wealthsimple chequing PDF: {value!r}") from exc


def _iso_date(value: str, *, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise AdapterError(f"invalid transaction {field} date: {value!r}") from exc


def _money(value: str) -> Decimal:
    match = _MONEY_RE.fullmatch(value.strip())
    if match is None:
        raise AdapterError(f"invalid Wealthsimple chequing CAD amount: {value!r}")
    try:
        magnitude = Decimal(match.group("amount").replace(",", ""))
    except InvalidOperation as exc:
        raise AdapterError(f"invalid Wealthsimple chequing CAD amount: {value!r}") from exc
    amount = -magnitude if match.group("negative") else magnitude
    return normalize_money(amount, field="Wealthsimple chequing CAD amount")


def _band_text(words: Sequence[_PositionedWord]) -> str:
    return _single_space(" ".join(word.text for word in words)).strip()


def _single_space(value: str) -> str:
    return re.sub(r"\s+", " ", value)
