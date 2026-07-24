"""Deterministic adapter for the American Express XLSX export."""

from __future__ import annotations

import re
from io import BytesIO
from typing import Any

import polars as pl
from openpyxl import load_workbook

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
from worker.models import AccountKind, ParsedFile, ParsedTransaction, ParseResult

_DATE_HEADERS = ("date", "transaction date", "booked date")
_DESCRIPTION_HEADERS = ("description", "merchant", "details")
_AMOUNT_HEADERS = ("amount", "transaction amount", "amount cad")
_FOREIGN_HEADERS = ("foreign spend amount", "foreign amount")
_REFERENCE_HEADERS = ("reference", "reference id", "ref")
_POSTED_DATE_HEADERS = ("posted date", "posting date")


class AmexXlsxAdapter:
    format = "xlsx"
    name = "amex_xlsx"

    def detect(self, file: ParsedFile) -> float:
        if file.extension not in {".xlsx", ".xlsm"}:
            return 0.0
        try:
            rows = self._read_rows(file)
        except Exception:
            return 0.0
        header = locate_header_row(
            rows,
            required_groups=(
                frozenset(_DATE_HEADERS),
                frozenset(_DESCRIPTION_HEADERS),
                frozenset(_AMOUNT_HEADERS),
            ),
        )
        if header is None:
            return 0.1
        normalized = {normalize_header(value) for value in rows[header]}
        amex_markers = {"foreign spend amount", "reference"}
        preamble = " ".join(str(cell) for row in rows[:header] for cell in row).lower()
        if "american express" in preamble or normalized.intersection(amex_markers):
            return 0.99
        return 0.72

    def parse(
        self,
        file: ParsedFile,
        *,
        account_kind: AccountKind = AccountKind.CREDIT_CARD,
    ) -> ParseResult:
        if account_kind is not AccountKind.CREDIT_CARD:
            raise AdapterError("Amex XLSX statements require a credit-card account")
        rows = self._read_rows(file)
        header_index = locate_header_row(
            rows,
            required_groups=(
                frozenset(_DATE_HEADERS),
                frozenset(_DESCRIPTION_HEADERS),
                frozenset(_AMOUNT_HEADERS),
            ),
        )
        if header_index is None:
            raise AdapterError("Amex XLSX header with Date, Description, and Amount was not found")

        headers = [normalize_header(cell) for cell in rows[header_index]]
        date_col = resolve_unique_column(headers, _DATE_HEADERS, field="booked date")
        description_col = resolve_unique_column(headers, _DESCRIPTION_HEADERS, field="description")
        amount_col = resolve_unique_column(headers, _AMOUNT_HEADERS, field="amount")
        foreign_col = resolve_unique_column(
            headers, _FOREIGN_HEADERS, field="foreign spend", required=False
        )
        reference_col = resolve_unique_column(
            headers, _REFERENCE_HEADERS, field="reference", required=False
        )
        posted_col = resolve_unique_column(
            headers, _POSTED_DATE_HEADERS, field="posted date", required=False
        )

        records: list[dict[str, Any]] = []
        for source_row in rows[header_index + 1 :]:
            if not any(value is not None and str(value).strip() for value in source_row):
                continue
            if _cell(source_row, date_col) in (None, ""):
                continue
            records.append(
                {
                    "booked": _cell(source_row, date_col),
                    "posted": _cell(source_row, posted_col),
                    "description": _cell(source_row, description_col),
                    "amount": _cell(source_row, amount_col),
                    "foreign": _cell(source_row, foreign_col),
                    "reference": _cell(source_row, reference_col),
                }
            )

        preamble = rows[: header_index + 1]
        slash_order = infer_slash_date_order(
            [
                value
                for record in records
                for value in (record.get("booked"), record.get("posted"))
                if value not in (None, "")
            ]
            + list(statement_period_date_values(preamble))
        )
        # Polars provides an explicit, columnar normalization boundary while
        # Decimal/date validation remains in the canonical Pydantic model.
        frame = pl.DataFrame(records, infer_schema_length=None) if records else pl.DataFrame()
        parsed_rows: list[ParsedTransaction] = []
        metadata = extract_statement_metadata(preamble, slash_date_order=slash_order)
        for record in frame.iter_rows(named=True):
            description = str(record["description"] or "").strip()
            if not description:
                raise AdapterError("transaction description is blank")
            amount = parse_decimal(record["amount"])
            enrichment: dict[str, Any] = {}
            if foreign := _parse_foreign_spend(record.get("foreign")):
                enrichment["foreign_spend"] = foreign
            parsed_rows.append(
                ParsedTransaction(
                    booked_date=parse_date(record["booked"], slash_order=slash_order),
                    posted_date=(
                        parse_date(record["posted"], slash_order=slash_order)
                        if record.get("posted")
                        else None
                    ),
                    description_raw=description,
                    amount_native=amount,
                    currency_native=metadata.currency,
                    external_ref=(
                        str(record["reference"]).strip() if record.get("reference") else None
                    ),
                    direction=infer_direction(description, amount),
                    enrichment=enrichment,
                )
            )

        if not parsed_rows:
            raise AdapterError("Amex XLSX contains no transaction rows")
        metadata = metadata_with_row_dates(metadata, [row.booked_date for row in parsed_rows])
        return ParseResult(adapter=self.name, rows=tuple(parsed_rows), statement=metadata)

    @staticmethod
    def _read_rows(file: ParsedFile) -> list[list[object]]:
        workbook = load_workbook(BytesIO(file.content), read_only=True, data_only=True)
        try:
            sheet = workbook.active
            return [list(row) for row in sheet.iter_rows(values_only=True)]
        finally:
            workbook.close()


def _cell(row: list[object], index: int | None) -> object | None:
    if index is None or index >= len(row):
        return None
    return row[index]


_FOREIGN_PATTERNS = (
    re.compile(r"^\s*([A-Z]{3})\s*\$?\s*([\d,]+(?:\.\d+)?)\s*$", re.IGNORECASE),
    re.compile(r"^\s*\$?\s*([\d,]+(?:\.\d+)?)\s*([A-Z]{3})\s*$", re.IGNORECASE),
    re.compile(r"^\s*([A-Z]{2})\$\s*([\d,]+(?:\.\d+)?)\s*$", re.IGNORECASE),
)


def _parse_foreign_spend(value: object) -> dict[str, str] | None:
    if value is None or not str(value).strip():
        return None
    text = str(value).strip()
    for index, pattern in enumerate(_FOREIGN_PATTERNS):
        if not (match := pattern.match(text)):
            continue
        if index == 1:
            amount, currency = match.group(1), match.group(2)
        else:
            currency, amount = match.group(1), match.group(2)
        currency = {"US": "USD", "CA": "CAD"}.get(currency.upper(), currency.upper())
        return {"amount": str(parse_decimal(amount)), "currency": currency}
    raise AdapterError(f"invalid Foreign Spend Amount: {value!r}")
