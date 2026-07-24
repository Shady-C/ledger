"""Deterministic, alias-based adapter for conventional statement CSV files."""

from __future__ import annotations

import csv
from collections.abc import Sequence
from decimal import Decimal
from io import StringIO
from typing import Any

import polars as pl

from worker.adapters.base import (
    AdapterError,
    extract_statement_metadata,
    infer_direction,
    infer_slash_date_order,
    locate_header_row,
    metadata_with_row_dates,
    normalize_header,
    parse_date,
    parse_decimal,
    parse_optional_flag,
    resolve_unique_column,
    statement_currency_evidence,
    statement_period_date_values,
)
from worker.models import AccountKind, Direction, ParsedFile, ParsedTransaction, ParseResult

DATE_HEADERS = ("date", "transaction date", "booked date", "booking date")
DESCRIPTION_HEADERS = ("description", "details", "memo", "merchant", "narrative")
AMOUNT_HEADERS = ("amount", "transaction amount", "value")
DEBIT_HEADERS = ("debit", "debits", "withdrawal", "withdrawals", "charge")
CREDIT_HEADERS = ("credit", "credits", "deposit", "deposits", "payment")
CURRENCY_HEADERS = ("currency", "currency code")
ORIGINAL_AMOUNT_HEADERS = (
    "original amount",
    "foreign amount",
    "foreign spend amount",
    "transaction amount original",
)
ORIGINAL_CURRENCY_HEADERS = (
    "original currency",
    "foreign currency",
    "transaction currency",
)
FX_FEE_HEADERS = (
    "fx fee",
    "foreign exchange fee",
    "currency conversion fee",
    "fx commission",
    "foreign exchange commission",
)
STANDALONE_FX_FEE_HEADERS = (
    "is fx fee",
    "standalone fx fee",
    "fx fee transaction",
)
REFERENCE_HEADERS = ("reference", "reference id", "transaction id")
POSTED_DATE_HEADERS = ("posted date", "posting date")


class GenericCsvAdapter:
    format = "csv"
    name = "generic_csv"

    def detect(self, file: ParsedFile) -> float:
        if file.extension != ".csv":
            return 0.0
        try:
            rows = self._read_rows(file.content)
        except (UnicodeDecodeError, csv.Error):
            return 0.0
        header = self._locate_header(rows)
        return 0.88 if header is not None else 0.15

    def parse(
        self,
        file: ParsedFile,
        *,
        account_kind: AccountKind = AccountKind.CREDIT_CARD,
    ) -> ParseResult:
        return self.parse_tabular_rows(self._read_rows(file.content), account_kind=account_kind)

    def parse_tabular_rows(
        self,
        rows: Sequence[Sequence[object]],
        *,
        account_kind: AccountKind = AccountKind.CREDIT_CARD,
    ) -> ParseResult:
        header_index = self._locate_header(rows)
        if header_index is None:
            raise AdapterError(
                "CSV header requires date, description, and amount or debit/credit columns"
            )
        headers = [normalize_header(value) for value in rows[header_index]]
        date_col = resolve_unique_column(headers, DATE_HEADERS, field="booked date")
        description_col = resolve_unique_column(headers, DESCRIPTION_HEADERS, field="description")
        amount_col = resolve_unique_column(headers, AMOUNT_HEADERS, field="amount", required=False)
        debit_col = resolve_unique_column(headers, DEBIT_HEADERS, field="debit", required=False)
        credit_col = resolve_unique_column(headers, CREDIT_HEADERS, field="credit", required=False)
        if amount_col is None and debit_col is None and credit_col is None:
            raise AdapterError("no amount, debit, or credit column found")
        if amount_col is not None and (debit_col is not None or credit_col is not None):
            raise AdapterError(
                "multiple amount representations make source sign semantics ambiguous"
            )
        if amount_col is not None and account_kind.is_asset:
            raise AdapterError(
                "signed Amount columns are ambiguous for asset accounts; "
                "use explicit debit/credit columns"
            )

        currency_col = resolve_unique_column(
            headers, CURRENCY_HEADERS, field="currency", required=False
        )
        original_amount_col = resolve_unique_column(
            headers, ORIGINAL_AMOUNT_HEADERS, field="original amount", required=False
        )
        original_currency_col = resolve_unique_column(
            headers, ORIGINAL_CURRENCY_HEADERS, field="original currency", required=False
        )
        fx_fee_col = resolve_unique_column(
            headers, FX_FEE_HEADERS, field="FX fee", required=False
        )
        standalone_fx_fee_col = resolve_unique_column(
            headers,
            STANDALONE_FX_FEE_HEADERS,
            field="standalone FX fee",
            required=False,
        )
        reference_col = resolve_unique_column(
            headers, REFERENCE_HEADERS, field="reference", required=False
        )
        posted_col = resolve_unique_column(
            headers, POSTED_DATE_HEADERS, field="posted date", required=False
        )
        records: list[dict[str, Any]] = []
        for row in rows[header_index + 1 :]:
            if not any(value is not None and str(value).strip() for value in row):
                continue
            if not _cell(row, date_col):
                continue
            records.append(
                {
                    "booked": _cell(row, date_col),
                    "posted": _cell(row, posted_col),
                    "description": _cell(row, description_col),
                    "amount": _cell(row, amount_col),
                    "debit": _cell(row, debit_col),
                    "credit": _cell(row, credit_col),
                    "currency": _cell(row, currency_col),
                    "original_amount": _cell(row, original_amount_col),
                    "original_currency": _cell(row, original_currency_col),
                    "fx_fee": _cell(row, fx_fee_col),
                    "is_fx_fee": _cell(row, standalone_fx_fee_col),
                    "reference": _cell(row, reference_col),
                }
            )

        preamble = rows[: header_index + 1]
        slash_format = infer_slash_date_order(
            [
                value
                for record in records
                for value in (record.get("booked"), record.get("posted"))
                if value not in (None, "")
            ]
            + list(statement_period_date_values(preamble))
        )
        metadata = extract_statement_metadata(preamble, slash_date_order=slash_format)
        labelled_statement_currency = statement_currency_evidence(preamble)
        frame = pl.DataFrame(records, infer_schema_length=None) if records else pl.DataFrame()
        parsed: list[ParsedTransaction] = []
        for record in frame.iter_rows(named=True):
            description = str(record["description"] or "").strip()
            if not description:
                raise AdapterError("transaction description is blank")
            amount, direction = _row_amount(record, account_kind=account_kind)
            original_amount_value = record.get("original_amount")
            original_currency_value = record.get("original_currency")
            original_present = original_amount_value not in (None, "")
            original_currency_present = original_currency_value not in (None, "")
            if original_present != original_currency_present:
                raise AdapterError(
                    "original amount and original currency must both be present on a row"
                )
            original_amount = None
            original_currency = None
            if original_present:
                magnitude = abs(parse_decimal(original_amount_value))
                original_amount = -magnitude if amount < 0 else magnitude
                original_currency = str(original_currency_value).strip().upper()
            resolved_direction = direction or infer_direction(description, amount)
            has_fx_fee_description = any(
                token in normalize_header(description)
                for token in (
                    "foreign exchange fee",
                    "fx fee",
                    "currency conversion fee",
                    "fx commission",
                    "exchange commission",
                )
            )
            has_inline_fee_value = record.get("fx_fee") not in (None, "")
            parsed_fx_fee = (
                abs(parse_decimal(record["fx_fee"])) if has_inline_fee_value else None
            )
            explicit_standalone = parse_optional_flag(
                record.get("is_fx_fee"), field="standalone FX fee"
            )
            is_fx_fee = (
                explicit_standalone
                if explicit_standalone is not None
                else (
                    has_fx_fee_description
                    and not original_present
                    and (parsed_fx_fee is None or parsed_fx_fee == abs(amount))
                )
            )
            if is_fx_fee and original_present:
                raise AdapterError("a standalone FX-fee row cannot contain original spend")
            if is_fx_fee:
                resolved_direction = Direction.FEE
            inline_fx_fee = parsed_fx_fee if not is_fx_fee else None
            parsed.append(
                ParsedTransaction(
                    booked_date=parse_date(record["booked"], slash_order=slash_format),
                    posted_date=(
                        parse_date(record["posted"], slash_order=slash_format)
                        if record.get("posted")
                        else None
                    ),
                    description_raw=description,
                    amount_native=amount,
                    currency_native=str(record.get("currency") or metadata.currency).upper(),
                    original_amount=original_amount,
                    original_currency=original_currency,
                    fx_fee_amount_native=inline_fx_fee,
                    is_fx_fee=is_fx_fee,
                    external_ref=(
                        str(record["reference"]).strip() if record.get("reference") else None
                    ),
                    direction=resolved_direction,
                )
            )
        if not parsed:
            raise AdapterError("CSV contains no transaction rows")
        row_currencies = {row.currency_native for row in parsed}
        if len(row_currencies) != 1:
            raise AdapterError("CSV mixes multiple native currencies")
        row_currency = next(iter(row_currencies))
        if (
            labelled_statement_currency is not None
            and labelled_statement_currency != row_currency
        ):
            raise AdapterError("statement balance currency differs from transaction currency")
        metadata = metadata.model_copy(update={"currency": row_currency})
        metadata = metadata_with_row_dates(metadata, [row.booked_date for row in parsed])
        return ParseResult(adapter=self.name, rows=tuple(parsed), statement=metadata)

    @staticmethod
    def _locate_header(rows: Sequence[Sequence[object]]) -> int | None:
        direct = locate_header_row(
            rows,
            required_groups=(
                frozenset(DATE_HEADERS),
                frozenset(DESCRIPTION_HEADERS),
                frozenset(AMOUNT_HEADERS),
            ),
        )
        if direct is not None:
            return direct
        for index, row in enumerate(rows):
            values = {normalize_header(cell) for cell in row}
            if (
                values.intersection(DATE_HEADERS)
                and values.intersection(DESCRIPTION_HEADERS)
                and (values.intersection(DEBIT_HEADERS) or values.intersection(CREDIT_HEADERS))
            ):
                return index
        return None

    @staticmethod
    def _read_rows(content: bytes) -> list[list[str]]:
        text = content.decode("utf-8-sig")
        sample = text[:8192]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        return [list(row) for row in csv.reader(StringIO(text), dialect)]


def _row_amount(
    record: dict[str, Any], *, account_kind: AccountKind
) -> tuple[Decimal, Direction | None]:
    if record.get("amount") not in (None, ""):
        return parse_decimal(record["amount"]), None
    debit_present = record.get("debit") not in (None, "")
    credit_present = record.get("credit") not in (None, "")
    if debit_present and credit_present:
        raise AdapterError("row contains both debit and credit amounts")
    if not debit_present and not credit_present:
        raise AdapterError("row contains no amount")
    source_amount = parse_decimal(record["debit"] if debit_present else record["credit"])
    if source_amount < 0:
        raise AdapterError("split debit/credit columns must contain unsigned magnitudes")
    if account_kind is AccountKind.CREDIT_CARD:
        return (source_amount if debit_present else -source_amount), None
    if debit_present:
        return -source_amount, Direction.DEBIT
    return source_amount, Direction.CREDIT


def _cell(row: Sequence[object], index: int | None) -> object | None:
    if index is None or index >= len(row):
        return None
    return row[index]
