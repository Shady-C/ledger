from __future__ import annotations

from decimal import Decimal
from io import BytesIO

from openpyxl import Workbook

from worker.adapters.generic_xlsx import GenericXlsxAdapter
from worker.models import AccountKind, ParsedFile


def _workbook_bytes(rows: list[list[object]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def test_deterministic_generic_xlsx_supports_asset_statement_and_three_layers() -> None:
    file = ParsedFile(
        name="synthetic-bank.xlsx",
        content=_workbook_bytes(
            [
                ["Currency", "TZS"],
                ["Opening Balance", "1000000.00 TZS"],
                [
                    "Date",
                    "Description",
                    "Debit",
                    "Credit",
                    "Currency",
                    "Original Amount",
                    "Original Currency",
                    "FX Fee",
                ],
                [
                    "2026-01-03",
                    "Synthetic USD purchase",
                    "270000.00",
                    None,
                    "TZS",
                    "100.00",
                    "USD",
                    "5000.00",
                ],
            ]
        ),
    )
    adapter = GenericXlsxAdapter()

    assert adapter.detect(file) == 0.88
    result = adapter.parse(file, account_kind=AccountKind.CHEQUING)

    assert result.adapter == "generic_xlsx_v1"
    assert result.statement.currency == "TZS"
    assert result.rows[0].amount_native == Decimal("-270000.00")
    assert result.rows[0].original_amount == Decimal("-100.00")
    assert result.rows[0].fx_fee_amount_native == Decimal("5000.00")
