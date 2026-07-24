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
    resolve_unique_column,
    statement_period_date_values,
)
from worker.models import AccountKind, Direction, ParsedFile, ParsedTransaction, ParseResult

DATE_HEADERS = ("date", "transaction date", "booked date", "booking date")
DESCRIPTION_HEADERS = ("description", "details", "memo", "merchant", "narrative")
AMOUNT_HEADERS = ("amount", "transaction amount", "value")
DEBIT_HEADERS = ("debit", "debits", "withdrawal", "withdrawals", "charge")
CREDIT_HEADERS = ("credit", "credits", "deposit", "deposits", "payment")
CURRENCY_HEADERS = ("currency", "currency code")
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
        frame = pl.DataFrame(records, infer_schema_length=None) if records else pl.DataFrame()
        parsed: list[ParsedTransaction] = []
        for record in frame.iter_rows(named=True):
            description = str(record["description"] or "").strip()
            if not description:
                raise AdapterError("transaction description is blank")
            amount, direction = _row_amount(record, account_kind=account_kind)
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
                    external_ref=(
                        str(record["reference"]).strip() if record.get("reference") else None
                    ),
                    direction=direction or infer_direction(description, amount),
                )
            )
        if not parsed:
            raise AdapterError("CSV contains no transaction rows")
        row_currencies = {row.currency_native for row in parsed}
        if len(row_currencies) != 1:
            raise AdapterError("CSV mixes multiple native currencies")
        metadata = metadata.model_copy(update={"currency": next(iter(row_currencies))})
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
